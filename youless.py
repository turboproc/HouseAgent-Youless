import os, sys

from twisted.web.client import getPage
from twisted.python.util import println

from twisted.protocols import basic
import ConfigParser
from houseagent.plugins import pluginapi
from twisted.internet import reactor, defer
from twisted.internet.task import LoopingCall
from twisted.python import log

# Platform specific imports
if os.name == "nt":
    import win32service
    import win32serviceutil
    import win32event
    import win32evtlogutil

class YoulessDevice(object):
    '''
    Abstract class to represent a YoulessDevice
    '''
    def __init__(self, id, type, subtype):
        self.id = id
        self.type = type
        self.subtype = subtype



class E_meter(YoulessDevice):
    '''
    Abstract class to represent a E-meter device.
    '''
    def __init__(self, id, type, subtype):
        YoulessDevice.__init__(self, id, type, subtype)
        self.counter = None
        
    def __repr__(self):
        return '[E_meter] id: %r, type: %r, subtype: %r, counter: %r' % (self.id, self.type, self.subtype, self.counter)


class YoulessProtocol(basic.LineReceiver):
    '''
    This class handles the Youless protocol, i.e. the wire level stuff.
    '''
    def __init__(self, wrapper):
        self.wrapper = wrapper
        self._devices = []
           
    def read_device(self):
	d = getPage("http://" + self.wrapper.addr +  "/a")
	d.addCallback(self._handle_data)
            
    def _handle_data(self, line):
        '''
        @param line: the raw line of data received.
        '''
        p = line.find("kWh")
        q = line.find("Watt")
        
        watt = line[p+4:q-1]        
        node_id = 1
        type = 'Youless'
        subtype = 'Youless E-meter'
            
        device = self._device_exists(id, type)
        
        if not device:
             device = E_meter(node_id, type, subtype)
             self._devices.append(device)

        log.msg("Received data from Youless e-meter; channel: %s, watt %s" % (node_id, watt))
                  
        values = {'Watt': str(watt)}
           
        self.wrapper.pluginapi.value_update(node_id, values)         
            
            
    def _device_exists(self, id, type):
        '''
        Helper function to check whether a device exists in the device list.
        @param id: the id of the device
        @param type: the type of the device
        '''
        for device in self._devices:
            if device.id == id and device.type == type:
                return device
            
        return False
        


class YoulessWrapper():

    def __init__(self):
        '''
        Load initial Youless configuration from youless.conf
        '''
        from houseagent.utils.generic import get_configurationpath
        config_path = "/etc/houseagent"
        
        config = ConfigParser.RawConfigParser()
        config.read(os.path.join(config_path, 'youless.conf'))
        self.addr = config.get("net", "addr")

        # Get broker information (RabbitMQ)
        self.broker_host = config.get("broker", "host")
        self.broker_port = config.getint("broker", "port")
        self.broker_user = config.get("broker", "username")
        self.broker_pass = config.get("broker", "password")
        self.broker_vhost = config.get("broker", "vhost")
        
        self.logging = config.getboolean('general', 'logging')
        self.id = config.get('general', 'id')
                
    def start(self):
        '''
        Function that starts the Youless plug-in. It handles the creation 
        of the plugin connection.
        '''
        callbacks = {'custom': self.cb_custom}
        
        self.pluginapi = pluginapi.PluginAPI(self.id, 'Youless', broker_host=self.broker_host, broker_port=self.broker_port, **callbacks)
        self.protocol = YoulessProtocol(self)
        self.pluginapi.ready()

	log.startLogging(open('/var/log/houseagent/youless.log','w'))
	
	log.msg("Started Youless plugin")


	lc = LoopingCall(self.protocol.read_device)
	lc.start(60)
        reactor.run(installSignalHandlers=0)
        return True
        
    def cb_custom(self, action, parameters):
        '''
        This function is a callback handler for custom commands
        received from the coordinator.
        @param action: the custom action to handle
        @param parameters: the parameters passed with the custom action
        '''
        if action == 'get_devices':
            print 'get_devices'
            devices = {}
            for dev in self.protocol._devices:
                devices[dev.id] = [dev.type, dev.subtype]
            d = defer.Deferred()
            d.callback(devices)

            return d


if os.name == "nt":    
    
    class JeelabsService(win32serviceutil.ServiceFramework):
        '''
        This class is a Windows Service handler, it's common to run
        long running tasks in the background on a Windows system, as such we
        use Windows services for HouseAgent.
        '''        
        _svc_name_ = "hajeelabs"
        _svc_display_name_ = "HouseAgent - Jeelabs Service"
        
        def __init__(self,args):
            win32serviceutil.ServiceFramework.__init__(self,args)
            self.hWaitStop=win32event.CreateEvent(None, 0, 0, None)
            self.isAlive=True
    
        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            reactor.stop()
            win32event.SetEvent(self.hWaitStop)
            self.isAlive=False
    
        def SvcDoRun(self):
            import servicemanager
                   
            win32evtlogutil.ReportEvent(self._svc_name_,servicemanager.PYS_SERVICE_STARTED,0,
            servicemanager.EVENTLOG_INFORMATION_TYPE,(self._svc_name_, ''))
    
            self.timeout=1000  # In milliseconds (update every second)
            jeelabs = JeelabsWrapper()
            
            if jeelabs.start():
                win32event.WaitForSingleObject(self.hWaitStop, win32event.INFINITE) 
    
            win32evtlogutil.ReportEvent(self._svc_name_,servicemanager.PYS_SERVICE_STOPPED,0,
                                        servicemanager.EVENTLOG_INFORMATION_TYPE,(self._svc_name_, ''))
    
            self.ReportServiceStatus(win32service.SERVICE_STOPPED)
    
            return

if __name__ == '__main__':
    
    if os.name == "nt":    
        
        if len(sys.argv) == 1:
            try:
    
                import servicemanager, winerror
                evtsrc_dll = os.path.abspath(servicemanager.__file__)
                servicemanager.PrepareToHostSingle(JeelabsService)
                servicemanager.Initialize('JeelabsService', evtsrc_dll)
                servicemanager.StartServiceCtrlDispatcher()
    
            except win32service.error, details:
                if details[0] == winerror.ERROR_FAILED_SERVICE_CONTROLLER_CONNECT:
                    win32serviceutil.usage()
        else:    
            win32serviceutil.HandleCommandLine(JeelabsService)
    else:
        youless = YoulessWrapper()
        youless.start()