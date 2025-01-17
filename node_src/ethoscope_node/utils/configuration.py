import os, json, datetime
import logging

users_keys = ['name', 'fullname', 'PIN', 'email', 'telephone',  'group', 'active', 'isAdmin', 'created']
incubators_keys = ['id', 'name', 'location', 'owner', 'description']


def migrate_conf_file(file_path, destination = '/etc/ethoscope/'):
    '''
    On Jan 30, 2024 we moved the configuration files to their own folder in /etc/ethoscope/ so that they could be mounted
    as volumes when using the node in a docker container. We need to migrate the files during the first update
    '''
    
    # Check if the file exists and move it if it does
    if os.path.isfile(file_path):
        logging.info(f"File {file_path} exists.")
        import shutil

        # Check if the directory exists, and if not, create it
        if not os.path.exists(destination):
            os.makedirs(destination)
            logging.info(f"Directory {destination} created.")

        # Construct the new file path
        new_file_path = os.path.join(destination, os.path.basename(file_path))

        # Move the file
        shutil.move(file_path, new_file_path)
        logging.info(f"File moved to {new_file_path}.")



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
                        
                  'sensors' : {},
                  
                  'commands' : {
                                 'command_1' : {'name' : 'List ethoscope files.', 'description' : 'Show ethoscope data folders on the node. Just an example of how to write a command', 'command' : 'ls -lh /ethoscope_data/results'}
                        },

                  'custom' :   {
                                 'UPDATE_SERVICE_URL' : 'http://localhost:8888'
                        }
                }

    def __init__(self, config_file = "/etc/ethoscope/ethoscope.conf"):
        migrate_conf_file('/etc/ethoscope.conf')
        self._config_file = config_file
        self.load()

    def _migrate_configuration_file(self):
        '''
        On Jan 30, 2024 we moved the configuration files to their own folder in /etc/ethoscope/ so that they could be mounted
        as volumes when using the node in a docker container. We need to migrate the files during the first update
        '''
        # Define the file and directory paths
        file_path = '/etc/ethoscope.conf'
        directory_path = '/etc/ethoscope/'

        # Check if the file exists
        if os.path.isfile(file_path):
            logging.info(f"File {file_path} exists.")
            import shutil

            # Check if the directory exists, and if not, create it
            if not os.path.exists(directory_path):
                os.makedirs(directory_path)
                logging.info(f"Directory {directory_path} created.")

            # Construct the new file path
            new_file_path = os.path.join(directory_path, os.path.basename(file_path))

            # Move the file
            shutil.move(file_path, new_file_path)
            logging.info(f"File moved to {new_file_path}.")


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
        self._settings[section].update(obj)
    
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
        # Extract the directory path
        config_dir = os.path.dirname(self._config_file)

        # Check if the directory exists, and create it if it does not
        if not os.path.exists(config_dir):
            os.makedirs(config_dir)
            logging.info(f"Directory '{config_dir}' did not exist and was created.")

        try:
            with open(self._config_file, 'w') as json_data_file:
                json.dump(self._settings, json_data_file, indent=4, sort_keys=True)
            
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
                    self.save()
            except:
                raise ValueError("File %s is not a valid configuration file" % self._config_file)
                
        return self._settings

    def custom(self, name=None):
        '''
        Returns the custom section, either in its entirety or the specified variable
        '''
        if not name:
            return self._settings['custom']
        else:
            return self._settings['custom'][name]


if __name__ == '__main__':

    c = EthoscopeConfiguration()
    c.load()
    
    c.addKey('commands', {'command_1' : {'name': 'Sync all data to Turing', 'description': 'Sync all the ethoscope data to turing', 'command': '/etc/cron.hourly/sync'}})
    c.addKey('commands', {'command_2' : {'name': 'Delete old files', 'description': 'Delete ethoscope data older than 180 days', 'command': 'find /ethoscope_data/results -type f -mtime +90 -exec rm {}\\;'}})
    c.addKey('commands', {'command_3' : {'name': 'List ethoscope files', 'description': 'Just used for debugging purposes', 'command': 'ls -h /ethoscope_data/results'}})

    print (c.listSections())
    print (c.content['commands'])

    c.save()
    
    
