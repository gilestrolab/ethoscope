(function() {
    var app = angular.module('flyApp');

    app.directive('tooltip', function($compile, $timeout) {
        return {
            restrict: 'A',
            link: function(scope, element, attrs) {
                // Create tooltip element
                const tooltipElement = angular.element('<div class="custom-tooltip">{{tooltipText}}</div>');
                tooltipElement.addClass('tooltip-hidden'); // Initially hidden
                element.after(tooltipElement);

                // Set tooltip text from the `tooltip` attribute
                let tooltipText = attrs.tooltip || ''; // Default to empty string
                scope.tooltipText = tooltipText;

                // Compile the tooltip element to enable Angular binding
                $compile(tooltipElement)(scope);

                // Tooltip visibility logic
                const showTooltip = () => {
                    tooltipElement.removeClass('tooltip-hidden');
                    tooltipElement.addClass('tooltip-visible');
                };

                const hideTooltip = () => {
                    tooltipElement.removeClass('tooltip-visible');
                    tooltipElement.addClass('tooltip-hidden');
                };

                // Attach mouseover and mouseleave events for tooltip visibility
                element.bind('mouseenter', () => {
                    scope.$apply(showTooltip);
                });

                element.bind('mouseleave', () => {
                    scope.$apply(hideTooltip);
                });

                // Clean up event listeners on destroy
                scope.$on('$destroy', () => {
                    element.unbind('mouseenter');
                    element.unbind('mouseleave');
                });
            }
        };
    });

    app.config(['$compileProvider', function($compileProvider) {
        $compileProvider.aHrefSanitizationWhitelist(/^\s*(https?|ftp|mailto|file|sms|tel|ssh):/);
    }]);

    app.controller('ethoscopeController', function($scope, $http, $routeParams, $interval, $timeout, $location) {

        device_id = $routeParams.device_id;
        //        var device_ip;

        $scope.node = {
            'users': {},
            'incubators': {}
        }

        $http.get('/node/users')
            .success(function(data, status, headers, config) {
                $scope.node['users'] = data;
            });

        $http.get('/node/incubators')
            .success(function(data, status, headers, config) {
                $scope.node['incubators'] = data;
            });

        $http.get('/sensors')
            .success(function(data, status, headers, config) {
                $scope.node['sensors'] = data;
            });


        $scope.device = {}; //the info about the device
        $scope.ethoscope = {}; // to control the device
        $scope.showLog = false;
        $scope.can_stream = false;
        $scope.isActive = false;
        //$scope.isExperimental = false;
        var refresh_data = false;
        var spStart = new Spinner(opts).spin();
        var starting_tracking = document.getElementById('starting');

        $http.get('/device/' + device_id + '/machineinfo').success(function(data) {
            $scope.machine_info = data;
        });

        $http.get('/device/' + device_id + '/data').success(function(data) {
            $scope.device = data;
            $scope.isActive = ($scope.device['name'].split("_").pop() != "000");
        });

        $http.get('/device/' + device_id + '/videofiles').success(function(data) {
            $scope.videofiles = data.filelist;
        });

        $http.get('/device/' + device_id + '/user_options').success(function(data) {
            $scope.user_options = {};
            $scope.can_stream = (typeof data.streaming !== 'undefined');
            $scope.user_options.tracking = data.tracking;
            $scope.user_options.recording = data.recording;
            $scope.user_options.update_machine = data.update_machine;
            
            // Load ROI templates from node and update dropdown options
            $scope.loadRoiTemplates();

            $scope.selected_options = {};
            $scope.selected_options.tracking = {};
            $scope.selected_options.recording = {};
            $scope.selected_options.update_machine = {};

            for (var k in data.tracking) {
                $scope.selected_options.tracking[k] = {};
                $scope.selected_options.tracking[k]['name'] = data.tracking[k][0]['name'];
                $scope.selected_options.tracking[k]['arguments'] = {};
                for (var j = 0; j < data.tracking[k][0]['arguments'].length; j++) {
                    $scope.selected_options.tracking[k]['arguments'][data.tracking[k][0]['arguments'][j]['name']] = data.tracking[k][0]['arguments'][j]['default'];
                }
            }
            
            // Initialize template file upload status
            $scope.template_file_status = "";
            $scope.uploaded_template_data = null;

            for (var k in data.recording) {
                $scope.selected_options.recording[k] = {};
                $scope.selected_options.recording[k]['name'] = data.recording[k][0]['name'];
                $scope.selected_options.recording[k]['arguments'] = {};
                for (var j = 0; j < data.recording[k][0]['arguments'].length; j++) {
                    $scope.selected_options.recording[k]['arguments'][data.recording[k][0]['arguments'][j]['name']] = data.recording[k][0]['arguments'][j]['default'];
                }
            }

            for (var k in data.update_machine) {
                $scope.selected_options.update_machine[k] = {};
                $scope.selected_options.update_machine[k]['name'] = data.update_machine[k][0]['name'];
                $scope.selected_options.update_machine[k]['arguments'] = {};
                for (var j = 0; j < data.update_machine[k][0]['arguments'].length; j++) {
                    $scope.selected_options.update_machine[k]['arguments'][data.update_machine[k][0]['arguments'][j]['name']] = data.update_machine[k][0]['arguments'][j]['default'];
                }
            }

        });


        $scope.ethoscope.update_user_options = function(optionType, name) {
            const data = $scope.user_options[optionType];

            // Iterate through the available options for the given type
            for (let i = 0; i < data[name].length; i++) {
                if (data[name][i]['name'] === $scope.selected_options[optionType][name]['name']) {
                    // Reset arguments for the selected option
                    $scope.selected_options[optionType][name]['arguments'] = {};

                    // Populate arguments for the selected option
                    for (let j = 0; j < data[name][i]['arguments'].length; j++) {
                        const argument = data[name][i]['arguments'][j];

                        if (argument['type'] === 'datetime') {
                            // Handle datetime arguments
                            $scope.selected_options[optionType][name]['arguments'][argument['name']] = [
                                moment(argument['default']).format('LLLL'),
                                argument['default']
                            ];
                        } else {
                            // Set default arguments for other types
                            $scope.selected_options[optionType][name]['arguments'][argument['name']] = argument['default'];
                        }
                    }
                }
            }
        };

        // Handling tracking options
        $scope.ethoscope.update_user_options.tracking = function(name) {
            $scope.ethoscope.update_user_options('tracking', name);
        };

        // Handling recording options
        $scope.ethoscope.update_user_options.recording = function(name) {
            $scope.ethoscope.update_user_options('recording', name);
        };

        // Handling update_machine options
        $scope.ethoscope.update_user_options.update_machine = function(name) {
            $scope.ethoscope.update_user_options('update_machine', name);
        };

        $scope.ethoscope.backup = function() {
            $http.post('/device/' + device_id + '/backup', data = {}).success(function(data) {
                $scope.device = data;
            })

        }

        $scope.ethoscope.SQLdump = function() {

            function recvinfo() {
                $http.get('/device/' + device_id + '/dumpSQLdb').success(function(data) {
                    $scope.SQLdumpStatus = data['Status'];
                    $scope.SQLdumpStarted = data['Started']
                })
            }
            var timer1 = setInterval(function() {
                if ($scope.SQLdumpStatus != 'Finished') {
                    recvinfo()
                } else {
                    clearInterval(timer1)
                }
            }, 2000);
        }

        $scope.ethoscope.testModule = function() {
            console.log("Asking ethoscope to test the attached module.");
            $http.post('/device/' + device_id + '/controls/test_module')
                .success(function(response) {
                    $scope.device.status = response.status;
                    window.location.reload();
                });

        }


        $scope.ethoscope.stream = function(option) {
            if ($scope.can_stream) {
                console.log("getting real time stream");
                $http.post('/device/' + device_id + '/controls/stream', data = {
                        "recorder": {
                            "name": "Streamer",
                            "arguments": {}
                        }
                    })
                    .success(function(response) {
                        $scope.device.status = response.status;
                        window.location.reload();
                    });
            }
        };

        $scope.ethoscope.convertvideos = function() {
            console.log("Asking ethoscope to convert any h264 chunks to local mp4");
            $http.post('/device/' + device_id + '/controls/convertvideos')
                .success(function(response) {
                    $scope.device.status = response.status;
                    window.location.reload();
                });

        };

        $scope.get_ip_of_sensor = function(location) {
            location = location.replace(/\s+/g, '_');
            for (sensor in $scope.node['sensors']) {
                if ($scope.node['sensors'][sensor]["location"] == location) {
                    return $scope.node['sensors'][sensor]["ip"];
                }
            }
        }


        $scope.ethoscope.start_tracking = function(option) {
            $("#startModal").modal('hide');
            spStart = new Spinner(opts).spin();
            starting_tracking.appendChild(spStart.el);

            for (opt in option) {
                for (arg in option[opt].arguments) {

                    //OBSOLETE? get only the second parameter in the time array. (linux timestamp).
                    //if(option[opt].arguments[arg][0] instanceof Date ){                        
                    //option[opt].arguments[arg]=option[opt].arguments[arg][1];
                    //}

                    //get the "formatted" field only from daterangepicker if it exist
                    if (option[opt].arguments[arg] != undefined && option[opt].arguments[arg].hasOwnProperty('formatted')) {
                        option[opt].arguments[arg] = option[opt].arguments[arg].formatted;
                    }
                }
            }

            //gets info about the sensor, if it is linked to a location            
            option["experimental_info"].arguments["sensor"] = $scope.get_ip_of_sensor(option["experimental_info"].arguments["location"]);

            // Check if we need to handle custom template transfer for FileBasedROIBuilder
            var templateName = null;
            var isCustomTemplate = false;
            
            if (option.roi_builder && option.roi_builder.arguments && option.roi_builder.arguments.template_name) {
                templateName = option.roi_builder.arguments.template_name;
                
                // Check if this is a custom template by looking at the selected option
                var selectedTemplateInfo = $scope.getSelectedTemplateInfo(templateName);
                isCustomTemplate = selectedTemplateInfo && selectedTemplateInfo.type === 'custom';
            }

            var startTrackingWithData = function() {
                console.log(option);
                
                //send options to the ethoscope and starts tracking
                $http.post('/device/' + device_id + '/controls/start', data = option)
                    .success(function(data) {
                        $scope.device.status = data.status;
                    });

                //refresh status
                $http.get('/devices').success(function(data) {
                    $http.get('/device/' + device_id + '/data').success(function(data) {
                        $scope.device = data;
                    });
                    $("#startModal").modal('hide');
                });
            };

            if (isCustomTemplate && templateName) {
                // For custom templates, ensure they're transferred to the device
                console.log("Custom template detected: " + templateName + ". Uploading to device if needed.");
                $scope.uploadTemplateToDevice(templateName, function(success) {
                    if (success) {
                        console.log("Custom template uploaded successfully");
                    } else {
                        console.log("Custom template upload failed, proceeding anyway");
                    }
                    startTrackingWithData();
                });
            } else {
                // For builtin templates, no transfer needed
                if (templateName) {
                    console.log("Builtin template detected: " + templateName + ". No transfer needed.");
                }
                startTrackingWithData();
            }
        };
        
        // Helper function to get template information by name
        $scope.getSelectedTemplateInfo = function(templateName) {
            // This would be populated from the dropdown options
            // For now, we can check if there are any custom templates
            if ($scope.available_templates) {
                for (var i = 0; i < $scope.available_templates.length; i++) {
                    if ($scope.available_templates[i].value === templateName) {
                        return $scope.available_templates[i];
                    }
                }
            }
            return null;
        };
        
        // Handle template selection change (show/hide file upload)
        $scope.handleTemplateChange = function(category, argName, value) {
            if (argName === 'template_name' && value === 'custom_upload') {
                // Show file upload for custom template
                var fileArg = null;
                var roiBuilderOptions = $scope.user_options.tracking[category];
                for (var i = 0; i < roiBuilderOptions.length; i++) {
                    if (roiBuilderOptions[i].name === $scope.selected_options.tracking[category]['name']) {
                        for (var j = 0; j < roiBuilderOptions[i].arguments.length; j++) {
                            if (roiBuilderOptions[i].arguments[j].name === 'template_file') {
                                roiBuilderOptions[i].arguments[j].hidden = false;
                                break;
                            }
                        }
                        break;
                    }
                }
            } else if (argName === 'template_name') {
                // Hide file upload for builtin templates
                var roiBuilderOptions = $scope.user_options.tracking[category];
                for (var i = 0; i < roiBuilderOptions.length; i++) {
                    if (roiBuilderOptions[i].name === $scope.selected_options.tracking[category]['name']) {
                        for (var j = 0; j < roiBuilderOptions[i].arguments.length; j++) {
                            if (roiBuilderOptions[i].arguments[j].name === 'template_file') {
                                roiBuilderOptions[i].arguments[j].hidden = true;
                                break;
                            }
                        }
                        break;
                    }
                }
            }
        };
        
        // Handle template file selection
        $scope.onTemplateFileSelect = function(files) {
            if (files && files.length > 0) {
                var file = files[0];
                if (file.type === 'application/json' || file.name.endsWith('.json')) {
                    $scope.template_file_status = "Reading file...";
                    var reader = new FileReader();
                    reader.onload = function(e) {
                        try {
                            var templateData = JSON.parse(e.target.result);
                            // Validate basic structure
                            if (templateData.template_info && templateData.roi_definition) {
                                $scope.uploaded_template_data = templateData;
                                $scope.template_file_status = "✓ Template loaded: " + (templateData.template_info.name || file.name);
                                // Set template_data argument
                                $scope.selected_options.tracking.roi_builder.arguments.template_data = templateData;
                                $scope.selected_options.tracking.roi_builder.arguments.template_name = null;
                                $scope.$apply();
                            } else {
                                $scope.template_file_status = "❌ Invalid template format";
                                $scope.$apply();
                            }
                        } catch (err) {
                            $scope.template_file_status = "❌ Invalid JSON file";
                            $scope.$apply();
                        }
                    };
                    reader.readAsText(file);
                } else {
                    $scope.template_file_status = "❌ Please select a .json file";
                }
            }
        };
        
        // Load ROI templates from node server
        $scope.loadRoiTemplates = function() {
            $http.get('/roi_templates').success(function(data) {
                // Store template information for later use
                $scope.available_templates = data.templates;
                
                // Update template dropdown options for FileBasedROIBuilder
                if ($scope.user_options && $scope.user_options.tracking && 
                    $scope.user_options.tracking.roi_builder) {
                    
                    for (var i = 0; i < $scope.user_options.tracking.roi_builder.length; i++) {
                        var roiBuilder = $scope.user_options.tracking.roi_builder[i];
                        
                        // Check if this is a FileBasedROIBuilder
                        if (roiBuilder.name === 'FileBasedROIBuilder' || 
                            roiBuilder.class === 'FileBasedROIBuilder') {
                            
                            // Find template_name argument
                            for (var j = 0; j < roiBuilder.arguments.length; j++) {
                                var arg = roiBuilder.arguments[j];
                                if (arg.name === 'template_name') {
                                    // Replace options with templates from node
                                    arg.options = data.templates.map(function(template) {
                                        return {
                                            value: template.value,
                                            text: template.text
                                        };
                                    });
                                    // Add custom upload option
                                    arg.options.push({
                                        value: "custom_upload",
                                        text: "Upload Custom Template..."
                                    });
                                    break;
                                }
                            }
                        }
                    }
                }
            }).error(function() {
                console.log("Could not load ROI templates from node server");
            });
        };
        
        // Upload template to device when needed
        $scope.uploadTemplateToDevice = function(templateName, callback) {
            $http.post('/device/' + device_id + '/upload_template', 
                      {template_name: templateName})
                .success(function(data) {
                    console.log("Template uploaded to device: " + templateName);
                    if (callback) callback(true);
                })
                .error(function(data, status) {
                    console.log("Failed to upload template to device: " + templateName);
                    if (callback) callback(false);
                });
        };

        $scope.ethoscope.start_recording = function(option) {
            //console.log(option)
            $("#recordModal").modal('hide');
            spStart = new Spinner(opts).spin();
            starting_tracking.appendChild(spStart.el);
            
            // Check if we need to upload template to device first
            var templateName = null;
            if (option.roi_builder && option.roi_builder.arguments && 
                option.roi_builder.arguments.template_name &&
                option.roi_builder.arguments.template_name !== 'custom_upload') {
                templateName = option.roi_builder.arguments.template_name;
            }
            
            var startRecording = function() {
                //get only the second parameter in the time array. (linux timestamp).
                for (opt in option) {
                    for (arg in option[opt].arguments) {
                        if (option[opt].arguments[arg][0] instanceof Date) {
                            option[opt].arguments[arg] = option[opt].arguments[arg][1];
                        }
                    }
                }

                $http.post('/device/' + device_id + '/controls/start_record', data = option)
                    .success(function(data) {
                        $scope.device.status = data.status;
                        $scope.device.countdown = data.autostop;
                    });

                $http.get('/devices').success(function(data) {
                    $http.get('/device/' + device_id + '/data').success(function(data) {
                        $scope.device = data;
                    });
                    $("#recordModal").modal('hide');
                });
            };
            
            // Upload template to device if needed, then start recording
            if (templateName) {
                $scope.uploadTemplateToDevice(templateName, function(success) {
                    if (success) {
                        startRecording();
                    } else {
                        // Template upload failed, but continue anyway
                        console.log("Warning: Template upload failed, proceeding with recording");
                        startRecording();
                    }
                });
            } else {
                startRecording();
            }
        };

        $scope.ethoscope.update_machine = function(option) {
            $("#changeInfo").modal('hide');
            $http.post('/device/' + device_id + '/machineinfo', data = option)
                .success(function(data) {
                    $scope.machine_info = data;
                    if (data.haschanged) {
                        $scope.ethoscope.alert("Some settings have changed. Please REBOOT your ethoscope now.");
                    }
                })
        };

        $scope.ethoscope.stop = function() {
            console.log("stopping")
            $http.post('/device/' + device_id + '/controls/stop', data = {})
                .success(function(data) {
                    $scope.device.status = data.status;
                });
        };

        $scope.ethoscope.download = function() {
            $http.get($scope.device.ip + ':9000/static' + $scope.result_files);
        };

        $scope.ethoscope.log = function() {

            $http.get('/device/' + device_id + '/machineinfo').success(function(data) {
                $scope.machine_info = data;
            });


            var log_file_path = ''
            if ($scope.showLog == false) {
                log_file_path = $scope.device.log_file;
                $http.post('/device/' + device_id + '/log', data = {
                        "file_path": log_file_path
                    })
                    .success(function(data, status, headers, config) {
                        $scope.log = data;
                        $scope.showLog = true;
                    });
            } else {
                $scope.showLog = false;
            }
        };

        $scope.ethoscope.poweroff = function() {
            //window.alert("Powering off... This tab will close when your device is turned off.")
            $http.post('/device/' + device_id + '/controls/poweroff', data = {})
                .success(function(data) {
                    $scope.device = data;
                    window.close()
                })

        };

        $scope.ethoscope.reboot = function() {
            console.log("rebooting");
            $http.post('/device/' + device_id + '/controls/reboot', data = {})
                .success(function(data) {
                    $scope.device = data;
                    window.close()
                })

        };

        $scope.ethoscope.restart = function() {
            console.log("restarting");
            $http.post('/device/' + device_id + '/controls/restart', data = {})
                .success(function(data) {
                    $scope.device = data;
                    //window.close()
                })

        };

        $scope.hasValidInteractor = function(device) {
            return (
                device.status === 'running' &&
                device.hasOwnProperty('interactor') &&
                device.interactor.name !== "<class 'ethoscope.stimulators.stimulators.DefaultStimulator'>"
            );
        };

        $scope.ethoscope.alert = function(message) {
            alert(message);
        };

        $scope.ethoscope.elapsedtime = function(t) {
            // Get the current timestamp
            var now = Math.floor(Date.now() / 1000);
            // Calculate the difference in seconds
            var elapsed = now - t;

            // Calculate the number of days left
            var days = Math.floor(elapsed / 86400);
            // After deducting the days calculate the number of hours left
            var hours = Math.floor((elapsed - (days * 86400)) / 3600);
            // After days and hours, how many minutes are left
            var minutes = Math.floor((elapsed - (days * 86400) - (hours * 3600)) / 60);
            // Finally how many seconds left after removing days, hours and minutes
            var secs = Math.floor(elapsed - (days * 86400) - (hours * 3600) - (minutes * 60));

            // Build the string based on the largest time component present
            var x = "";
            if (days > 0) {
                x += days + " days, ";
            }
            if (hours > 0 || days > 0) { // Include hours if there are also days
                x += hours + "h, ";
            }
            if (minutes > 0 || hours > 0 || days > 0) { // Include minutes if there are also hours or days
                x += minutes + "min, ";
            }
            x += secs + "s"; // Always include seconds

            return x;
        };

        $scope.ethoscope.readable_url = function(url) {
            //start tooltips
            $('[data-toggle="tooltip"]').tooltip()
            readable = url.split("/");
            len = readable.length;
            readable = ".../" + readable[len - 1];
            return readable;
        };

        $scope.ethoscope.start_date_time = function(unix_timestamp) {
            var date = new Date(unix_timestamp * 1000);
            return date.toUTCString();
        };

        var $attempt = 0;
        var refresh = function() {
            if (document.visibilityState == "visible") {
                $http.get('/device/' + device_id + '/data')
                    .success(function(data) {
                        $scope.device = data;
                        $scope.node_datetime = "Node Time"
                        $scope.device_datetime = "Device Time"
                        if ("current_timestamp" in data) {
                            $scope.device_timestamp = new Date(data.current_timestamp * 1000);
                            $scope.device_datetime = $scope.device_timestamp.toUTCString();
                            $http.get('/node/timestamp').success(function(data_node) {
                                node_t = data_node.timestamp;
                                node_time = new Date(node_t * 1000);
                                $scope.node_datetime = node_time.toUTCString();
                                $scope.delta_t_min = Math.abs((node_t - data.current_timestamp) / 60);

                                // Tries twice to adjust time remotely - if it does not manage we assume an old ethoscope version and we give up
                                if (($scope.delta_t_min > 3) && ($attempt < 3)) {
                                    $scope.ethoscope.update_machine({
                                        'machine_options': {
                                            arguments: {
                                                'datetime': new Date().getTime() / 1000
                                            },
                                            name: 'datetime'
                                        }
                                    });
                                    $attempt = $attempt + 1;
                                    console.log("Trying to force time update on the ethoscope. Attempt: " + $attempt);
                                };
                            });
                        }

                        $scope.device.url_img = "/device/" + $scope.device.id + "/last_img" + '?' + Math.floor(new Date().getTime() / 1000.0);
                        $scope.device.url_stream = '/device/' + device_id + '/stream';

                        //TODO: this needs to be fixed to point to local server upload!
                        $scope.device.url_upload = "http://" + $scope.device.ip + ":9000/upload/" + $scope.device.id;

                        //$scope.device.ip = device_ip;
                        status = $scope.device.status
                        if (typeof spStart != undefined) {
                            if (status != 'initialising' && status != 'stopping') {
                                spStart.stop();
                            }
                        }
                    });
            }
        }

        refresh_data = $interval(refresh, 6000);
        //clear interval when scope is destroyed
        $scope.$on("$destroy", function() {
            $interval.cancel(refresh_data);
            //clearInterval(refresh_data);
        });

    });

})()