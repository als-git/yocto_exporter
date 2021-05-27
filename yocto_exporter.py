#!/usr/bin/python3
#
# yocto_exporter: a Prometheus export for YoctoPuce USB sensor modules.
#
# requirements:
#   - Python3 Prometheus client library (Debian: python3-prometheus-client)
#   - YoctoPuce Python libraries: https://www.yoctopuce.com/EN/libraries.php
#     expected to be installed at: /opt/yoctolib_python/Sources
#
# commandline arguments:
#   - just one: debug - this dumps the found sensors on startup
#
# It listens on 0.0.0.0:8000/tcp by default.
#
# This exporter iterates:
#   - over all USB connected YoctoPuce sensor modules it finds
#     - over all sensors connected to the module
# while ignoring sensor 0, as this is the datalogger which we don't care about.
#
# Currently, the following sensor types are supported:
# - module internal:
#   - usb_current: USB module current consumption
#   - luminosity: USB module beacon luminosity
# - module sensors:
#   - pressure: ambient air pressure
#   - temperature: module temperature
#   - humidity: ambient air humidity
#   - light: light sensor output
# - exporter internals
#   - request_processing_seconds: time spent processing requests
#   - sensor_read_time: time spent in the last sensor reading loop
#   - sensor_read_passes: numbers of sensor reading loop iterations
#   - yapi_exceptions: number of exception from YAPI during sensor read
#
# Implementation details:
# Normally, a Prometheus exporters aquires the data it exports when it is
# asked for it (while being scraped). There already is (at least) one for
# the YoctoPuce sensors: # https://github.com/brian-maloney/yocto-exporter.git
# Except .. this approach isn't very stable, as I found. When scraping at a
# 5s interval, there is a noticeable number of failed scrapes, either because
# it takes too long to read all the sensors in realtime or because there are
# transient errors from the YAPI.
#
# So this exporter decouples scraping an data collection: After the http
# server has been started, in an endless loop, every 4s the data collector
# loop kicks off and updates the exported variables. Exception thrown by
# the YAPI get noted, counted and then ignored, as they are transients.
# I'm not entirely sure what causes those (device not found, I/O errors in
# the USB layer, timeouts during device request), but I suspect the USB
# implementation in the sensor modules might be less than perfect.
#
#

import sys, os, time

sys.path.append(os.path.join("/opt", "yoctolib_python", "Sources"))

from prometheus_client import start_http_server, Counter, Gauge, Summary
from yocto_api import YModule, YRefParam, YAPI, YAPI_Exception


HTTP_PORT = 8000

REQUEST_TIME = Summary('request_processing_seconds',
                       'Time spent processing request')

UsbCurrent = Gauge('usb_current', 'module USB current',
                   ['hardware_id', 'unit'])

Luminosity = Gauge('luminosity', 'module beacon luminosity',
                   ['hardware_id', 'unit'])
Pressure = Gauge('pressure', 'air pressure', ['hardware_id', 'unit'])
Temperature = Gauge('temperature', 'air temperature', ['hardware_id', 'unit'])
Humidity = Gauge('humidity', 'air humidity', ['hardware_id', 'unit'])
Light = Gauge('light', 'light', ['hardware_id', 'unit'])

SensorReadTime = Gauge('sensor_read_time', 'time spend reading sensors/pass',
                       ['unit'])
SensorReadPasses = Counter('sensor_read_passes',
                           'number of sensor read passes')
YAPIExceptions = Counter('yapi_exceptions', 'number exceptions from YAPI')



def find_and_dump_info():
  """Finds modules & sensors and does an info dump."""

  modules = []

  module = YModule.FirstModule()
  while module:
    print('module : %s is a %s ' % (module.get_serialNumber(),
                                    module.get_productName()))
    modules.append(module)
    module = module.nextModule()

  for module in modules:
    module_serial = module.get_serialNumber()
    module_name = module.get_productName()
    function_count = module.functionCount()
    print("module %s:" % module_name)
    print("            luminosity %s" % module.get_luminosity())
    print("            current %s mA" % module.get_usbCurrent())
    print("            hardware id %s" % module.get_hardwareId())
    print("            friendly name %s" % module.get_friendlyName())
  
    print("%s.%s has %s functions" % (module_serial, module_name, function_count))
    for function_id in range(0, function_count):
      function_type = module.functionType(function_id)
      function_name = module.functionName(function_id)
      function_value = module.functionValue(function_id)
      print("  %s = %s (%s) is %s" % (function_id, function_type, function_name, function_value))
 

@REQUEST_TIME.time()
def collect_gauges():
  # discover modules
  modules = []
  start_time = time.time()
  module = YModule.FirstModule()
  while (module):
    modules.append(module)
    module = module.nextModule()


  # iterate over modules
  for module in modules:
    # discover module info and update gauges
    module_name = module.get_friendlyName()
    hardware_id = '%s.current' % module_name
    usb_current = module.get_usbCurrent()
    UsbCurrent.labels(hardware_id=hardware_id, unit='mA').set(usb_current)
    hardware_id = '%s.luminosity' % module_name
    luminosity = module.get_luminosity()
    Luminosity.labels(hardware_id=hardware_id, unit='%').set(luminosity)

    # iterate over functions
    function_count = module.functionCount()
    for function_id in range(1, function_count):  # 0 is datalogger
      function_type = module.functionType(function_id)
      if function_type == 'Temperature':
        hardware_id = '%s.temperature' % module_name
        temperature = module.functionValue(function_id)
        Temperature.labels(hardware_id=hardware_id, unit='Celsius').set(temperature)
      if function_type == 'Pressure':
        hardware_id = '%s.pressure' % module_name
        pressure = module.functionValue(function_id)
        Pressure.labels(hardware_id=hardware_id, unit='mbar').set(pressure)
      if function_type == 'Humidity':
        hardware_id = '%s.humidity' % module_name
        humidity = module.functionValue(function_id)
        Humidity.labels(hardware_id=hardware_id, unit='% RH').set(humidity)
      if function_type == 'LightSensor':
        hardware_id = '%s.light' % module_name
        light = module.functionValue(function_id)
        Light.labels(hardware_id=hardware_id, unit='lux').set(light)

  end_time = time.time()
  sensor_read_time = end_time - start_time
  SensorReadTime.labels(unit='s').set(sensor_read_time)
  SensorReadPasses.inc()


def main():
  # Setup the API to use local USB devices
  errmsg = YRefParam()
  if YAPI.RegisterHub("usb", errmsg) != YAPI.SUCCESS:
      sys.exit("RegisterHub error: " + str(errmsg))

  time.sleep(2)

  if len(sys.argv) > 1:
    if sys.argv[1] == 'debug':
      find_and_dump_info()

  # pre-load exported variables so we have something to show
  collect_gauges()
  start_http_server(HTTP_PORT)
  print('HTTP server started on port %s, collection loop running.'% HTTP_PORT)
  while True:
    time.sleep(5)
    try:
      collect_gauges()
    except YAPI_Exception as exception:
      # Catch, count & ignore, those are transients presumable due to USB fun.
      YAPIExceptions.inc()

if __name__ == '__main__':
  main()



