(function(){
    var installationWizardController = function($scope, $http, $timeout, $location){
        
        console.log('Installation Wizard Controller loaded');
        
        // Initialize scope variables
        $scope.setupStatus = {};
        $scope.currentStep = 1;
        $scope.totalSteps = 9;
        $scope.isLoading = false;
        $scope.errorMessage = '';
        $scope.successMessage = '';
        $scope.isReconfigureMode = false;
        
        // Step data models
        $scope.basicInfo = {
            hostname: '',
            dataDir: '/ethoscope_data',
            configDir: '/etc/ethoscope'
        };
        
        $scope.adminUser = {
            username: '',
            fullname: '',
            email: '',
            pin: '',
            telephone: '',
            labname: '',
            replaceUser: null
        };
        
        $scope.additionalUsers = [];
        $scope.newUser = {};
        $scope.editingUser = {};
        $scope.editingUserIndex = -1;
        
        $scope.incubators = [];
        $scope.newIncubator = {};
        $scope.editingIncubator = {};
        $scope.editingIncubatorIndex = -1;
        
        $scope.tunnel = {
            enabled: false,
            mode: 'custom',  // 'custom' (free) or 'ethoscope_net' (paid)
            token: '',
            node_id: 'auto',
            domain: 'ethoscope.net',
            custom_domain: ''
        };
        
        $scope.notifications = {
            smtp: {
                enabled: false,
                host: 'localhost',
                port: 587,
                use_tls: true,
                username: '',
                password: '',
                from_email: 'ethoscope@localhost',
                test_email: ''
            },
            mattermost: {
                enabled: false,
                server_url: '',
                bot_token: '',
                channel_id: ''
            }
        };
        
        $scope.virtualSensor = {
            enabled: false,
            sensor_name: 'virtual-sensor',
            location: 'Lab',
            weather_location: '',
            api_key: ''
        };
        
        $scope.systemInfo = {};
        $scope.existingUsers = {};
        
        // Step definitions
        $scope.steps = [
            { number: 1, title: 'Welcome', description: 'Introduction and system check', icon: 'fa-home' },
            { number: 2, title: 'Basic Setup', description: 'Configure basic system settings', icon: 'fa-cog' },
            { number: 3, title: 'Admin User', description: 'Create administrator account', icon: 'fa-user-shield' },
            { number: 4, title: 'Users', description: 'Add additional users (optional)', icon: 'fa-users' },
            { number: 5, title: 'Incubators', description: 'Configure incubators (optional)', icon: 'fa-thermometer-half' },
            { number: 6, title: 'Virtual Sensor', description: 'Configure virtual sensor (optional)', icon: 'fa-cloud-sun' },
            { number: 7, title: 'Remote Access', description: 'Setup internet tunnel for remote access (optional)', icon: 'fa-globe' },
            { number: 8, title: 'Notifications', description: 'Setup email and chat notifications (optional)', icon: 'fa-bell' }
        ];
        
        // Initialize the wizard
        $scope.init = function() {
            console.log('Installation Wizard init() called');
            
            // Check if we're in reconfigure mode (URL parameter or query string)
            try {
                // Check URL parameters in hash or search
                var search = window.location.search || '';
                var hash = window.location.hash || '';
                
                console.log('Current URL - search:', search, 'hash:', hash);
                
                if (search.indexOf('reconfigure=true') !== -1 || 
                    hash.indexOf('reconfigure=true') !== -1) {
                    $scope.isReconfigureMode = true;
                    console.log('Reconfigure mode enabled');
                }
            } catch (e) {
                console.warn('Error checking reconfigure mode:', e);
                // Continue without reconfigure mode
            }
            
            $scope.loadSetupStatus();
            $scope.loadSystemInfo();
            
            // Load existing configuration if in reconfigure mode
            if ($scope.isReconfigureMode) {
                $scope.loadExistingConfig();
            }
        };
        
        // Load setup status from API
        $scope.loadSetupStatus = function() {
            $scope.isLoading = true;
            $http.get('/setup/status')
                .then(function(response) {
                    $scope.setupStatus = response.data;
                    
                    // If setup is already completed and not in reconfigure mode, redirect to home
                    if ($scope.setupStatus.completed && !$scope.isReconfigureMode) {
                        $scope.showMessage('Setup is already completed. Redirecting to main interface...', 'success');
                        $timeout(function() {
                            $location.path('/');
                        }, 2000);
                        return;
                    }
                    
                    // Load existing admin users for replacement option
                    if ($scope.setupStatus.system_info && $scope.setupStatus.system_info.admin_users > 0) {
                        $scope.loadExistingUsers();
                    }
                })
                .catch(function(error) {
                    $scope.showMessage('Error loading setup status: ' + (error.data?.message || error.statusText), 'error');
                })
                .finally(function() {
                    $scope.isLoading = false;
                });
        };
        
        // Load system information
        $scope.loadSystemInfo = function() {
            $http.get('/setup/system-info')
                .then(function(response) {
                    $scope.systemInfo = response.data;
                    
                    // Set default values from system info
                    if ($scope.systemInfo.hostname) {
                        $scope.basicInfo.hostname = $scope.systemInfo.hostname;
                    }
                })
                .catch(function(error) {
                    console.error('Error loading system info:', error);
                });
        };
        
        // Load existing users for admin replacement option
        $scope.loadExistingUsers = function() {
            $http.get('/node/users')
                .then(function(response) {
                    $scope.existingUsers = response.data;
                })
                .catch(function(error) {
                    console.error('Error loading existing users:', error);
                });
        };
        
        // Load existing configuration for reconfigure mode
        $scope.loadExistingConfig = function() {
            console.log('Loading existing configuration for reconfigure mode');
            $http.get('/setup/current-config')
                .then(function(response) {
                    if (response.data.result === 'success') {
                        var config = response.data.config;
                        
                        // Load folder settings
                        if (config.folders) {
                            if (config.folders.results) {
                                $scope.basicInfo.dataDir = config.folders.results.replace('/results', '');
                            }
                            // Note: config dir is typically read-only, so we don't change it
                        }
                        
                        // Load admin user settings
                        if (config.admin_user) {
                            $scope.adminUser.username = config.admin_user.username || '';
                            $scope.adminUser.fullname = config.admin_user.fullname || '';
                            $scope.adminUser.email = config.admin_user.email || '';
                            $scope.adminUser.pin = config.admin_user.pin || '';
                            $scope.adminUser.telephone = config.admin_user.telephone || '';
                            $scope.adminUser.labname = config.admin_user.labname || '';
                        }
                        
                        // Load tunnel settings
                        if (config.tunnel) {
                            $scope.tunnel.enabled = config.tunnel.enabled || false;
                            $scope.tunnel.mode = config.tunnel.mode || 'custom';
                            $scope.tunnel.token = config.tunnel.token || ''; // Load masked token if configured
                            $scope.tunnel.node_id = config.tunnel.node_id || 'auto';
                            $scope.tunnel.domain = config.tunnel.domain || 'ethoscope.net';
                            $scope.tunnel.custom_domain = config.tunnel.custom_domain || '';
                        }
                        
                        // Load notification settings
                        if (config.notifications) {
                            // SMTP settings
                            if (config.notifications.smtp) {
                                $scope.notifications.smtp.enabled = config.notifications.smtp.enabled || false;
                                $scope.notifications.smtp.host = config.notifications.smtp.host || 'localhost';
                                $scope.notifications.smtp.port = config.notifications.smtp.port || 587;
                                $scope.notifications.smtp.use_tls = config.notifications.smtp.use_tls !== false;
                                $scope.notifications.smtp.username = config.notifications.smtp.username || '';
                                $scope.notifications.smtp.password = config.notifications.smtp.password || ''; // Load masked password if configured
                                $scope.notifications.smtp.from_email = config.notifications.smtp.from_email || 'ethoscope@localhost';
                            }
                            
                            // Mattermost settings
                            if (config.notifications.mattermost) {
                                $scope.notifications.mattermost.enabled = config.notifications.mattermost.enabled || false;
                                $scope.notifications.mattermost.server_url = config.notifications.mattermost.server_url || '';
                                $scope.notifications.mattermost.bot_token = config.notifications.mattermost.bot_token || ''; // Load masked token if configured
                                $scope.notifications.mattermost.channel_id = config.notifications.mattermost.channel_id || '';
                            }
                        }
                        
                        // Load existing users
                        if (config.users && Array.isArray(config.users)) {
                            $scope.additionalUsers = config.users;
                        }
                        
                        // Load existing incubators
                        if (config.incubators && Array.isArray(config.incubators)) {
                            $scope.incubators = config.incubators;
                        }
                        
                        // Load virtual sensor settings
                        if (config.virtual_sensor) {
                            $scope.virtualSensor.enabled = config.virtual_sensor.enabled || false;
                            $scope.virtualSensor.sensor_name = config.virtual_sensor.sensor_name || 'virtual-sensor';
                            $scope.virtualSensor.location = config.virtual_sensor.location || 'Lab';
                            $scope.virtualSensor.weather_location = config.virtual_sensor.weather_location || '';
                            $scope.virtualSensor.api_key = config.virtual_sensor.api_key || '';
                        }
                        
                        console.log('Existing configuration loaded successfully');
                    } else {
                        console.warn('Failed to load existing configuration:', response.data.message);
                    }
                })
                .catch(function(error) {
                    console.error('Error loading existing configuration:', error);
                });
        };
        
        // Navigation functions
        $scope.nextStep = function() {
            if ($scope.currentStep < $scope.totalSteps) {
                $scope.currentStep++;
                $scope.clearMessages();
            }
        };
        
        $scope.previousStep = function() {
            if ($scope.currentStep > 1) {
                $scope.currentStep--;
                $scope.clearMessages();
            }
        };
        
        $scope.goToStep = function(stepNumber) {
            if (stepNumber >= 1 && stepNumber <= $scope.totalSteps) {
                $scope.currentStep = stepNumber;
                $scope.clearMessages();
            }
        };
        
        // Step validation
        $scope.isStepValid = function(stepNumber) {
            switch(stepNumber) {
                case 1:
                    return true; // Welcome step is always valid
                case 2:
                    return $scope.basicInfo.dataDir && $scope.basicInfo.configDir;
                case 3:
                    return $scope.adminUser.username && $scope.adminUser.email && $scope.adminUser.fullname;
                case 4:
                    return true; // Additional users are optional
                case 5:
                    return true; // Incubators are optional
                case 6:
                    if (!$scope.virtualSensor.enabled) return true; // If disabled, always valid
                    return $scope.virtualSensor.sensor_name && $scope.virtualSensor.location; // Name and location required when enabled
                case 7:
                    if (!$scope.tunnel.enabled) return true; // If disabled, always valid
                    if (!$scope.tunnel.token) return false; // Token always required
                    if ($scope.tunnel.mode === 'custom' && !$scope.tunnel.custom_domain) return false; // Custom domain required for free mode
                    return true;
                case 8:
                    return true; // Notifications are optional
                default:
                    return false;
            }
        };
        
        // Step processing functions
        $scope.processBasicInfo = function() {
            if (!$scope.isStepValid(2)) {
                $scope.showMessage('Please fill in all required fields.', 'error');
                return;
            }
            
            $scope.isLoading = true;
            var data = {
                folders: {
                    results: $scope.basicInfo.dataDir + '/results',
                    video: $scope.basicInfo.dataDir + '/videos',
                    temporary: '/tmp/ethoscope'
                }
            };
            
            $http.post('/setup/basic-info', data)
                .then(function(response) {
                    if (response.data.result === 'success') {
                        $scope.showMessage('Basic configuration saved successfully.', 'success');
                        $scope.nextStep();
                    } else {
                        $scope.showMessage('Error: ' + (response.data.message || 'Unknown error'), 'error');
                    }
                })
                .catch(function(error) {
                    $scope.showMessage('Error saving configuration: ' + (error.data?.message || error.statusText), 'error');
                })
                .finally(function() {
                    $scope.isLoading = false;
                });
        };
        
        $scope.processAdminUser = function() {
            if (!$scope.isStepValid(3)) {
                $scope.showMessage('Please fill in all required fields.', 'error');
                return;
            }
            
            $scope.isLoading = true;
            var data = angular.copy($scope.adminUser);
            
            $http.post('/setup/admin-user', data)
                .then(function(response) {
                    if (response.data.result === 'success') {
                        $scope.showMessage('Admin user created successfully.', 'success');
                        $scope.nextStep();
                    } else {
                        $scope.showMessage('Error: ' + (response.data.message || 'Unknown error'), 'error');
                    }
                })
                .catch(function(error) {
                    $scope.showMessage('Error creating admin user: ' + (error.data?.message || error.statusText), 'error');
                })
                .finally(function() {
                    $scope.isLoading = false;
                });
        };
        
        // Additional user management
        $scope.addUser = function() {
            if (!$scope.newUser.username || !$scope.newUser.email) {
                $scope.showMessage('Username and email are required for additional users.', 'error');
                return;
            }
            
            $scope.isLoading = true;
            
            $http.post('/setup/add-user', $scope.newUser)
                .then(function(response) {
                    if (response.data.result === 'success') {
                        $scope.additionalUsers.push(angular.copy($scope.newUser));
                        $scope.newUser = {};
                        $scope.showMessage('User added successfully.', 'success');
                        $('#addUserModal').modal('hide');
                    } else {
                        $scope.showMessage('Error: ' + (response.data.message || 'Unknown error'), 'error');
                    }
                })
                .catch(function(error) {
                    $scope.showMessage('Error adding user: ' + (error.data?.message || error.statusText), 'error');
                })
                .finally(function() {
                    $scope.isLoading = false;
                });
        };
        
        // Edit user - populate the edit modal with existing data
        $scope.editUser = function(index) {
            $scope.editingUser = angular.copy($scope.additionalUsers[index]);
            $scope.editingUserIndex = index;
        };
        
        // Update user
        $scope.updateUser = function() {
            if (!$scope.editingUser.username || !$scope.editingUser.email) {
                $scope.showMessage('Username and email are required.', 'error');
                return;
            }
            
            $scope.isLoading = true;
            
            var updateData = angular.copy($scope.editingUser);
            updateData.original_username = $scope.additionalUsers[$scope.editingUserIndex].username;
            
            $http.post('/setup/update-user', updateData)
                .then(function(response) {
                    if (response.data.result === 'success') {
                        $scope.additionalUsers[$scope.editingUserIndex] = angular.copy($scope.editingUser);
                        $scope.editingUser = {};
                        $scope.editingUserIndex = -1;
                        $scope.showMessage('User updated successfully.', 'success');
                        $('#editUserModal').modal('hide');
                    } else {
                        $scope.showMessage('Error: ' + (response.data.message || 'Unknown error'), 'error');
                    }
                })
                .catch(function(error) {
                    $scope.showMessage('Error updating user: ' + (error.data?.message || error.statusText), 'error');
                })
                .finally(function() {
                    $scope.isLoading = false;
                });
        };
        
        // Incubator management
        $scope.addIncubator = function() {
            if (!$scope.newIncubator.name) {
                $scope.showMessage('Incubator name is required.', 'error');
                return;
            }
            
            $scope.isLoading = true;
            
            $http.post('/setup/add-incubator', $scope.newIncubator)
                .then(function(response) {
                    if (response.data.result === 'success') {
                        $scope.incubators.push(angular.copy($scope.newIncubator));
                        $scope.newIncubator = {};
                        $scope.showMessage('Incubator added successfully.', 'success');
                        $('#addIncubatorModal').modal('hide');
                    } else {
                        $scope.showMessage('Error: ' + (response.data.message || 'Unknown error'), 'error');
                    }
                })
                .catch(function(error) {
                    $scope.showMessage('Error adding incubator: ' + (error.data?.message || error.statusText), 'error');
                })
                .finally(function() {
                    $scope.isLoading = false;
                });
        };
        
        // Edit incubator - populate the edit modal with existing data
        $scope.editIncubator = function(index) {
            $scope.editingIncubator = angular.copy($scope.incubators[index]);
            $scope.editingIncubatorIndex = index;
            console.log('Editing incubator:', $scope.editingIncubator);
        };
        
        // Update incubator
        $scope.updateIncubator = function() {
            console.log('updateIncubator called');
            console.log('editingIncubator:', $scope.editingIncubator);
            
            if (!$scope.editingIncubator.name) {
                $scope.showMessage('Incubator name is required.', 'error');
                return;
            }
            
            $scope.isLoading = true;
            
            var updateData = angular.copy($scope.editingIncubator);
            updateData.original_name = $scope.incubators[$scope.editingIncubatorIndex].name;
            
            console.log('Sending update data:', updateData);
            console.log('Making request to /setup/update-incubator');
            
            $http.post('/setup/update-incubator', updateData)
                .then(function(response) {
                    console.log('Update response:', response.data);
                    if (response.data.result === 'success') {
                        $scope.incubators[$scope.editingIncubatorIndex] = angular.copy($scope.editingIncubator);
                        $scope.editingIncubator = {};
                        $scope.editingIncubatorIndex = -1;
                        $scope.showMessage('Incubator updated successfully.', 'success');
                        $('#editIncubatorModal').modal('hide');
                    } else {
                        $scope.showMessage('Error: ' + (response.data.message || 'Unknown error'), 'error');
                    }
                })
                .catch(function(error) {
                    console.log('Update error:', error);
                    $scope.showMessage('Error updating incubator: ' + (error.data?.message || error.statusText), 'error');
                })
                .finally(function() {
                    $scope.isLoading = false;
                });
        };
        
        // Tunnel configuration
        $scope.processTunnel = function() {
            $scope.isLoading = true;
            
            $http.post('/setup/tunnel', $scope.tunnel)
                .then(function(response) {
                    if (response.data.result === 'success') {
                        // Move to next step
                        $scope.nextStep();
                    } else {
                        $scope.showMessage('Error: ' + (response.data.message || 'Unknown error'), 'error');
                    }
                })
                .catch(function(error) {
                    $scope.showMessage('Error saving tunnel configuration: ' + (error.data?.message || error.statusText), 'error');
                })
                .finally(function() {
                    $scope.isLoading = false;
                });
        };
        
        // Notification configuration
        $scope.processNotifications = function() {
            $scope.isLoading = true;
            
            $http.post('/setup/notifications', $scope.notifications)
                .then(function(response) {
                    if (response.data.result === 'success') {
                        // Move to final step instead of showing message
                        $scope.nextStep();
                    } else {
                        $scope.showMessage('Error: ' + (response.data.message || 'Unknown error'), 'error');
                    }
                })
                .catch(function(error) {
                    $scope.showMessage('Error saving notifications: ' + (error.data?.message || error.statusText), 'error');
                })
                .finally(function() {
                    $scope.isLoading = false;
                });
        };
        
        // Process virtual sensor configuration
        $scope.processVirtualSensor = function() {
            if (!$scope.isStepValid(6)) {
                $scope.showMessage('Please fill in required fields.', 'error');
                return;
            }
            
            $scope.isLoading = true;
            $scope.clearMessages();
            
            $http.post('/setup/virtual-sensor', $scope.virtualSensor)
                .then(function(response) {
                    $scope.showMessage('Virtual sensor configuration saved!', 'success');
                    $scope.nextStep();
                })
                .catch(function(error) {
                    $scope.showMessage('Error saving virtual sensor: ' + (error.data?.message || error.statusText), 'error');
                })
                .finally(function() {
                    $scope.isLoading = false;
                });
        };
        
        // Test virtual sensor weather API
        $scope.testVirtualSensor = function() {
            if (!$scope.virtualSensor.weather_location || !$scope.virtualSensor.api_key) {
                $scope.showMessage('Weather location and API key are required for testing.', 'error');
                return;
            }
            
            $scope.isLoading = true;
            $scope.clearMessages();
            
            var testData = {
                weather_location: $scope.virtualSensor.weather_location,
                api_key: $scope.virtualSensor.api_key
            };
            
            $http.post('/setup/test-weather-api', testData)
                .then(function(response) {
                    var data = response.data;
                    if (data.success) {
                        $scope.showMessage('Weather API test successful! Temperature: ' + 
                            data.temperature.toFixed(1) + '°C, Humidity: ' + 
                            data.humidity.toFixed(0) + '%', 'success');
                    } else {
                        $scope.showMessage('Weather API test failed: ' + data.message, 'error');
                    }
                })
                .catch(function(error) {
                    $scope.showMessage('Weather API test failed: ' + (error.data?.message || error.statusText), 'error');
                })
                .finally(function() {
                    $scope.isLoading = false;
                });
        };
        
        // Test notification functions
        $scope.testSMTP = function() {
            if (!$scope.notifications.smtp.host) {
                $scope.showMessage('SMTP host is required for testing.', 'error');
                return;
            }
            
            $scope.isLoading = true;
            var testConfig = angular.copy($scope.notifications.smtp);
            // Use admin user email as test recipient
            testConfig.test_email = $scope.adminUser.email || testConfig.from_email;
            
            // Set a 10 second timeout for SMTP test
            var timeoutPromise = $timeout(function() {
                $scope.isLoading = false;
                $scope.showMessage('SMTP test timed out. Please check your SMTP configuration.', 'error');
            }, 10000);
            
            $http.post('/setup/test-notifications', {
                type: 'smtp',
                config: testConfig
            })
                .then(function(response) {
                    $timeout.cancel(timeoutPromise);
                    if (response.data.result === 'success') {
                        $scope.showMessage('SMTP test successful: ' + response.data.message, 'success');
                    } else {
                        $scope.showMessage('SMTP test failed: ' + response.data.message, 'error');
                    }
                })
                .catch(function(error) {
                    $timeout.cancel(timeoutPromise);
                    $scope.showMessage('SMTP test error: ' + (error.data?.message || error.statusText), 'error');
                })
                .finally(function() {
                    $scope.isLoading = false;
                });
        };
        
        $scope.testMattermost = function() {
            if (!$scope.notifications.mattermost.server_url || !$scope.notifications.mattermost.bot_token) {
                $scope.showMessage('Server URL and bot token are required for testing Mattermost.', 'error');
                return;
            }
            
            $scope.isLoading = true;
            
            $http.post('/setup/test-notifications', {
                type: 'mattermost',
                config: $scope.notifications.mattermost
            })
                .then(function(response) {
                    if (response.data.result === 'success') {
                        $scope.showMessage('Mattermost test successful! Message sent to channel.', 'success');
                    } else {
                        $scope.showMessage('Mattermost test failed: ' + response.data.message, 'error');
                    }
                })
                .catch(function(error) {
                    $scope.showMessage('Mattermost test error: ' + (error.data?.message || error.statusText), 'error');
                })
                .finally(function() {
                    $scope.isLoading = false;
                });
        };
        
        // Complete setup
        $scope.completeSetup = function() {
            $scope.isLoading = true;
            
            $http.post('/setup/complete', {})
                .then(function(response) {
                    if (response.data.result === 'success') {
                        var message = $scope.isReconfigureMode ? 
                            'System reconfiguration completed successfully! Redirecting to main interface...' :
                            'Installation wizard completed successfully! Redirecting to main interface...';
                        $scope.showMessage(message, 'success');
                        $timeout(function() {
                            // Force redirect to home page
                            window.location.href = '/';
                        }, 2000);
                    } else {
                        $scope.showMessage('Error completing setup: ' + (response.data.message || 'Unknown error'), 'error');
                    }
                })
                .catch(function(error) {
                    $scope.showMessage('Error completing setup: ' + (error.data?.message || error.statusText), 'error');
                })
                .finally(function() {
                    $scope.isLoading = false;
                });
        };
        
        // Reset setup for testing
        $scope.resetSetup = function() {
            if (!confirm('Are you sure you want to reset the setup? This will mark the system as unconfigured.')) {
                return;
            }
            
            $scope.isLoading = true;
            
            $http.post('/setup/reset', {})
                .then(function(response) {
                    if (response.data.result === 'success') {
                        $scope.showMessage('Setup has been reset successfully.', 'success');
                        $scope.isReconfigureMode = false;
                        $scope.loadSetupStatus(); // Reload status
                    } else {
                        $scope.showMessage('Error resetting setup: ' + (response.data.message || 'Unknown error'), 'error');
                    }
                })
                .catch(function(error) {
                    $scope.showMessage('Error resetting setup: ' + (error.data?.message || error.statusText), 'error');
                })
                .finally(function() {
                    $scope.isLoading = false;
                });
        };
        
        // Utility functions
        $scope.showMessage = function(message, type) {
            $scope.clearMessages();
            if (type === 'success') {
                $scope.successMessage = message;
            } else {
                $scope.errorMessage = message;
            }
            
            // Auto-clear messages after 5 seconds
            $timeout(function() {
                $scope.clearMessages();
            }, 5000);
        };
        
        $scope.clearMessages = function() {
            $scope.errorMessage = '';
            $scope.successMessage = '';
        };
        
        $scope.getProgressPercentage = function() {
            return ($scope.currentStep / $scope.totalSteps) * 100;
        };
        
        // Get computed node ID for tunnel preview
        $scope.getComputedNodeId = function() {
            if ($scope.tunnel.node_id === 'auto') {
                var adminUsername = $scope.adminUser.username || 'admin';
                return 'node-' + adminUsername.toLowerCase();
            }
            return $scope.tunnel.node_id || 'node-admin';
        };
        
        // Get effective domain for tunnel preview
        $scope.getEffectiveDomain = function() {
            if ($scope.tunnel.mode === 'ethoscope_net') {
                return 'ethoscope.net';
            }
            return $scope.tunnel.custom_domain || 'your-domain.com';
        };
        
        // Get full tunnel URL preview
        $scope.getTunnelPreview = function() {
            return $scope.getComputedNodeId() + '.' + $scope.getEffectiveDomain();
        };
        
        // Generate username from full name
        $scope.generateUsername = function(fullname, targetObj) {
            if (fullname && targetObj) {
                // Create username from full name (lowercase, replace spaces with dots)
                var username = fullname.toLowerCase()
                    .replace(/[^a-z\s]/g, '') // Remove non-alphabetic characters except spaces
                    .replace(/\s+/g, '.') // Replace spaces with dots
                    .replace(/\.+/g, '.') // Replace multiple dots with single dot
                    .replace(/^\.|\.$/g, ''); // Remove leading/trailing dots
                
                targetObj.username = username;
            }
        };
        
        // Initialize the wizard when controller loads
        $scope.init();
    };

    // Register the controller
    angular.module('flyApp').controller('installationWizardController', 
        ['$scope', '$http', '$timeout', '$location', installationWizardController]);
})();