#!/usr/bin/python2

import sys
import os
import time

sys.path.append(os.path.join("/opt", "yoctolib_python", "Sources"))
from prometheus_client import start_http_server, Counter, Gauge, Summary



from yocto_api import *
from yocto_hubport import *

REQUEST_TIME = Summary('request_processing_seconds', 'Time spent processing request')

UsbCurrent = Gauge('usb_current', 'module USB current', ['hardware_id', 'unit'])
Luminosity = Gauge('luminosity', 'module beacon luminosity', ['hardware_id', 'unit'])
Pressure = Gauge('pressure', 'air pressure', ['hardware_id', 'unit'])
Temperature = Gauge('temperature', 'air temperature', ['hardware_id', 'unit'])
Humidity = Gauge('humidity', 'air humidity', ['hardware_id', 'unit'])
Light = Gauge('light', 'light', ['hardware_id', 'unit'])
SensorReadTime = Gauge('sensor_read_time', 'time spend reading sensors/pass', ['unit'])
SensorReadPasses = Counter('sensor_read_passes', 'number of sensor read passes')
YAPIExceptions = Counter('yapi_exceptions', 'number exceptions from YAPI')

# Setup the API to use local USB devices
errmsg = YRefParam()
if YAPI.RegisterHub("usb", errmsg) != YAPI.SUCCESS:
    sys.exit("RegisterHub error: " + str(errmsg))

time.sleep(2)

modules = []
Gauges = {}

module = YModule.FirstModule()
while (module):
  print("module : %s is a %s " % (module.get_serialNumber(), module.get_productName()))
  modules.append(module)
  module = module.nextModule()

print("modules: %s" % modules)

gauges = {}

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


collect_gauges()
start_http_server(8888)
while True:
  time.sleep(3)
  try:
    collect_gauges()
  except YAPI_Exception as exception:
    YAPIExceptions.inc()
    print('caught yocto_api.YAPI_Exception: %s' % exception)



