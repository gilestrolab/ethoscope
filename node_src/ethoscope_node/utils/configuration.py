import os, json, datetime
import logging

users_keys = ['name', 'fullname', 'PIN', 'email', 'telephone',  'group', 'active', 'isAdmin', 'created']
incubators_keys = ['id', 'name', 'location', 'owner', 'description']


class EthoscopeConfiguration(object):
    '''
    Handles the ethoscope configuration parameters
    Data are stored in and retrieved from a JSON configuration file
    '''
    _settings = { 
                  'folders' : {
                                    'results' : {'path' : '/ethoscope_data/results', 'description' : 'Where tracking data will be saved by the backup daemon.'},
                                    'video' : {'path' : '/ethoscope_data/videos', 'description' : 'Where video chunks (h264) will be saved by the backup daemon'},
                                    'temporary' : {'path' : '/ethoscope_data/results', 'description' : 'A temporary location for downloading data.'} 
                        },
                        
                  'users' :   {
                                    'admin' : {'id' : 1, 'name' : 'admin', 'fullname' : '', 'PIN' : 9999, 'email' : '', 'telephone' : '', 'group': '', 'active' : False, 'isAdmin' : True, 'created' : datetime.datetime.now().timestamp() }
                        },
                        
                  'incubators': {
                                    'incubator 1' : {'id' : 1, 'name' : 'Incubator 1', 'location' : '', 'owner' : '', 'description' : ''}
                        },
                        
                  'sensors' : {} 
                                    
                        }

    def __init__(self, config_file = "/etc/ethoscope.conf"):
        self._config_file = config_file
        self.load()

    def addSection(self, section):
        if section not in self._settings:
            self._settings[section] = {}
        else:
            raise ValueError ("Section %s is already present" % section)
            
    def listSections(self):
        return [k for k in self._settings.keys()]

    def listSubSection(self, section):
        return [k for k in self._settings[section].keys()]

    
    def addKey(self, section, obj):
        self._settings[section] = obj
    
    def addUser(self, userdata):
        name = userdata['name']
        try:
            self._settings['users'][name] = userdata
            self._settings['users'][name]['created'] = datetime.datetime.now().timestamp()
            self.save()
            return {'result' : 'success', 'data' : self._settings['users'] }
        except:   
            raise Exception ("Some issue assigning the values")
            return {'result' : 'failure', 'data' : "Some issue assigning the values" }


    def addIncubator(self, incubatordata):
        name = incubatordata['name']
        try:
            self._settings['incubators'][name] = incubatordata
            self.save()
            return {'result' : 'success', 'data' : self._settings['incubators'] }
        except:   
            raise Exception ("Some issue assigning the values")
            return {'result' : 'failure', 'data' : "Some issue assigning the values" }

    def addSensor(self, sensordata):
        name = sensordata['name']
        try:
            self._settings['sensors'][name] = sensordata
            self.save()
            return {'result' : 'success', 'data' : self._settings['sensors'] }
        except:   
            raise Exception ("Some issue assigning the values")
            return {'result' : 'failure', 'data' : "Some issue assigning the values" }

    
    @property
    def content(self):
        return self._settings

    @property
    def file_exists(self):
        '''
        '''
        return os.path.exists(self._config_file)
        
    def save(self):
        '''
        Save settings to default json file
        '''
        try:
            with open(self._config_file, 'w') as json_data_file:
                json.dump(self._settings, json_data_file)
            
            logging.info('Saved ethoscope configuration file to %s' % self._config_file)
        
        except:
            raise ValueError ('Problem writing to file % s' % self._config_file)
    
    def load(self):
        '''
        Reads saved configuration folders settings from json configuration file
        If file does not exist, creates default settings
        '''
        
        if not self.file_exists : self.save()
                
        else:
            try:
                with open(self._config_file, 'r') as json_data_file:
                    self._settings.update ( json.load(json_data_file) )
            except:
                raise ValueError("File %s is not a valid configuration file" % self._config_file)
                
        return self._settings


if __name__ == '__main__':

    c = configuration()
    print (c.listSections())
    #c.addSection('Users')
    c.addKey('Users', 'Name', )
    c.save()
    print (c.key['folders']['results_dir'])
    
    
