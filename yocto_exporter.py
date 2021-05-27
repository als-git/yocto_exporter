#!/usr/bin/python3
"""yocto_exporter: a Prometheus exporter for YoctoPuce sensor modules."""
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


import sys
import os
import time

import prometheus_client as p_c

# I need to frobnicate the import path first.
# pylint: disable=C0413
sys.path.append(os.path.join("/opt", "yoctolib_python", "Sources"))
import yocto_api as y_a
# pylint: enable=C0413


# Our listening port for incoming scrapes.
HTTP_PORT = 8000


# A whole pile of variables for Prometheus to scrape.

# The declarations below are _variables_, not constants, _and_ they
# follow the style guide.
# pylint: disable=C0103

# request processing time
request_time = p_c.Summary('request_processing_seconds',
                           'Time spent processing request')

# module internal state
usb_current = p_c.Gauge('usb_current', 'module USB current',
                        ['hardware_id', 'unit'])

luminosity = p_c.Gauge('luminosity', 'module beacon luminosity',
                       ['hardware_id', 'unit'])
pressure = p_c.Gauge('pressure', 'air pressure', ['hardware_id', 'unit'])
temperature = p_c.Gauge('temperature', 'air temperature',
                        ['hardware_id', 'unit'])
humidity = p_c.Gauge('humidity', 'air humidity', ['hardware_id', 'unit'])
light = p_c.Gauge('light', 'light', ['hardware_id', 'unit'])

# exporter state
sensor_read_time = p_c.Gauge('sensor_read_time',
                             'time spend reading sensors/pass', ['unit'])
sensor_read_passes = p_c.Counter('sensor_read_passes',
                                 'number of sensor read passes')
yapi_exceptions = p_c.Counter('yapi_exceptions', 'number exceptions from YAPI')

# pylint: enable=C0103


def find_and_dump_info():
  """Finds modules & sensors and does an info dump."""
  module = y_a.YModule.FirstModule()
  while module:
    print('module : %s is a %s ' % (module.get_serialNumber(),
                                    module.get_productName()))

    module_serial = module.get_serialNumber()
    module_name = module.get_productName()
    function_count = module.functionCount()
    print("module %s:" % module_name)
    print("            luminosity %s" % module.get_luminosity())
    print("            current %s mA" % module.get_usbCurrent())
    print("            hardware id %s" % module.get_hardwareId())
    print("            friendly name %s" % module.get_friendlyName())
    print("%s.%s has %s functions" % (module_serial, module_name,
                                      function_count))
    for function_id in range(0, function_count):
      function_type = module.functionType(function_id)
      function_value = module.functionValue(function_id)
      print("  %s = %s is %s" % (function_id, function_type, function_value))

    module = module.nextModule()


@request_time.time()
def collect_gauges():
  """Find modules & sensors, update gauges from sensor values."""
  # discover modules
  start_time = time.time()
  module = y_a.YModule.FirstModule()
  while module:
    # discover module info and update gauges
    module_name = module.get_friendlyName()
    hardware_id = '%s.current' % module_name
    usb_current_value = module.get_usbCurrent()
    usb_current.labels(hardware_id=hardware_id,
                       unit='mA').set(usb_current_value)
    hardware_id = '%s.luminosity' % module_name
    luminosity_value = module.get_luminosity()
    luminosity.labels(hardware_id=hardware_id,
                      unit='%').set(luminosity_value)

    # iterate over functions
    function_count = module.functionCount()
    for function_id in range(1, function_count):  # 0 is datalogger
      function_type = module.functionType(function_id)
      if function_type == 'Temperature':
        hardware_id = '%s.temperature' % module_name
        temperature_value = module.functionValue(function_id)
        temperature.labels(hardware_id=hardware_id,
                           unit='Celsius').set(temperature_value)
      if function_type == 'Pressure':
        hardware_id = '%s.pressure' % module_name
        pressure_value = module.functionValue(function_id)
        pressure.labels(hardware_id=hardware_id,
                        unit='mbar').set(pressure_value)
      if function_type == 'Humidity':
        hardware_id = '%s.humidity' % module_name
        humidity_value = module.functionValue(function_id)
        humidity.labels(hardware_id=hardware_id,
                        unit='% RH').set(humidity_value)
      if function_type == 'LightSensor':
        hardware_id = '%s.light' % module_name
        light_value = module.functionValue(function_id)
        light.labels(hardware_id=hardware_id, unit='lux').set(light_value)

    module = module.nextModule()

  end_time = time.time()
  sensor_read_time_value = end_time - start_time
  sensor_read_time.labels(unit='s').set(sensor_read_time_value)
  sensor_read_passes.inc()


def main():
  """Main entry point."""
  # Setup the API to use local USB devices
  errmsg = y_a.YRefParam()
  if y_a.YAPI.RegisterHub("usb", errmsg) != y_a.YAPI.SUCCESS:
    sys.exit("RegisterHub error: " + str(errmsg))

  time.sleep(2)

  if len(sys.argv) > 1:
    if sys.argv[1] == 'debug':
      find_and_dump_info()
    if sys.argv[1] == 'dumpsensors':
      find_and_dump_info()
      sys.exit(0)

  # pre-load exported variables so we have something to show
  collect_gauges()
  p_c.start_http_server(HTTP_PORT)
  print('HTTP server started on port %s, collection loop running.'% HTTP_PORT)
  while True:
    time.sleep(5)
    try:
      collect_gauges()
    except y_a.YAPI_Exception:
      # Catch, count & ignore, those are transients presumable due to USB fun.
      yapi_exceptions.inc()

if __name__ == '__main__':
  main()
