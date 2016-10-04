(function(){
var app = angular.module('flyApp');

app.directive('tooltip', function(){
    return {
        restrict: 'A',
        link: function(scope, element, attrs){
            $(element).hover(function(){
                // on mouseenter
                $(element).tooltip('show');
            }, function(){
                // on mouseleave
                $(element).tooltip('hide');
            });
        }
    };
});

app.controller('ethoscopeController', function($scope, $http, $routeParams, $interval, $timeout, $location)  {
        device_id = $routeParams.device_id;
//        var device_ip;
        $scope.device = {}; //the info about the device
        $scope.ethoscope = {}; // to control the device
        var refresh_data = false;
        var spStart= new Spinner(opts).spin();
        var starting_tracking= document.getElementById('starting');


        $http.get('/device/'+device_id+'/data').success(function(data){
            $scope.device = data;
        });

        $http.get('/device/'+device_id+'/user_options').success(function(data){
            $scope.user_options = {};
            $scope.user_options.tracking= data.tracking;
            $scope.user_options.recording= data.recording;

            $scope.selected_options = {};
            $scope.selected_options.tracking = {};
            $scope.selected_options.recording = {};

            for (var k in data.tracking){
                $scope.selected_options.tracking[k]={};
                $scope.selected_options.tracking[k]['name']=data.tracking[k][0]['name'];
                $scope.selected_options.tracking[k]['arguments']={};
                for(var j=0;j<data.tracking[k][0]['arguments'].length; j++){
                        $scope.selected_options.tracking[k]['arguments'][data.tracking[k][0]['arguments'][j]['name']]=data.tracking[k][0]['arguments'][j]['default'];
                }
            }

            for (var k in data.recording){
                $scope.selected_options.recording[k]={};
                $scope.selected_options.recording[k]['name']=data.recording[k][0]['name'];
                $scope.selected_options.recording[k]['arguments']={};
                for(var j=0;j<data.recording[k][0]['arguments'].length; j++){
                        $scope.selected_options.recording[k]['arguments'][data.recording[k][0]['arguments'][j]['name']]=data.recording[k][0]['arguments'][j]['default'];
                }
            }
        });


        $scope.ethoscope.update_user_options = {};

        $scope.ethoscope.update_user_options.tracking = function(name){
            data=$scope.user_options;
            for (var i=0;i<data.tracking[name].length;i++){
                if (data.tracking[name][i]['name']== $scope.selected_options.tracking[name]['name']){
                    $scope.selected_options.tracking[name]['arguments']={};
                    for(var j=0;j<data.tracking[name][i]['arguments'].length; j++){
                        if (data.tracking[name][i]['arguments'][j]['type']=='datetime'){
                          $scope.selected_options.tracking[name]['arguments'][data.tracking[name][i]['arguments'][j]['name']]=[];
                          $scope.selected_options.tracking[name]['arguments'][data.tracking[name][i]['arguments'][j]['name']][0]=moment(data.tracking[name][i]['arguments'][j]['default']).format('LLLL');
                          $scope.selected_options.tracking[name]['arguments'][data.tracking[name][i]['arguments'][j]['name']][1]=data.tracking[name][i]['arguments'][j]['default'];
                          console.log($scope.selected_options.tracking[name]['arguments'][data.tracking[name][i]['arguments'][j]['name']]);
                        } else {
                            $scope.selected_options.tracking[name]['arguments'][data.tracking[name][i]['arguments'][j]['name']]=data.tracking[name][i]['arguments'][j]['default'];
                        }

                    }
                }
            }
        }


        $scope.ethoscope.update_user_options.recording = function(name){
            data=$scope.user_options;
            for (var i=0;i<data.recording[name].length;i++){
                if (data.recording[name][i]['name']== $scope.selected_options.recording[name]['name']){
                    $scope.selected_options.recording[name]['arguments']={};
                    for(var j=0;j<data.recording[name][i]['arguments'].length; j++){
                        if (data.recording[name][i]['arguments'][j]['type']=='datetime'){
                          $scope.selected_options.recording[name]['arguments'][data.recording[name][i]['arguments'][j]['name']]=[];
                          $scope.selected_options.recording[name]['arguments'][data.recording[name][i]['arguments'][j]['name']][0]=moment(data.recording[name][i]['arguments'][j]['default']).format('LLLL');
                            $scope.selected_options.recording[name]['arguments'][data.recording[name][i]['arguments'][j]['name']][1]=data.recording[name][i]['arguments'][j]['default'];
                            console.log($scope.selected_options.recording[name]['arguments'][data.recording[name][i]['arguments'][j]['name']]);
                        }else{
                            $scope.selected_options.recording[name]['arguments'][data.recording[name][i]['arguments'][j]['name']]=data.recording[name][i]['arguments'][j]['default'];
                        }

                    }
                }
            }
        }

        $scope.ethoscope.start_tracking = function(option){
            $("#startModal").modal('hide');
            spStart= new Spinner(opts).spin();
            starting_tracking.appendChild(spStart.el);

            for (opt in option){
                for(arg in option[opt].arguments){
                    
                    //OBSOLETE? get only the second parameter in the time array. (linux timestamp).
                    //if(option[opt].arguments[arg][0] instanceof Date ){                        
                        //option[opt].arguments[arg]=option[opt].arguments[arg][1];
                    //}
                    
                    //get the "formatted" field only from daterangepicker if it exist
                    if(option[opt].arguments[arg].hasOwnProperty('formatted')) {
                        option[opt].arguments[arg] = option[opt].arguments[arg].formatted;
                    }
                    console.log(option[opt].arguments[arg]);
                }
            }

            $http.post('/device/'+device_id+'/controls/start', data=option)
                 .success(function(data){$scope.device.status = data.status;});
            $http.get('/devices').success(function(data){
                    $http.get('/device/'+device_id+'/data').success(function(data){
                        $scope.device = data;
                    });
                 $("#startModal").modal('hide');
            });

        };

        $scope.ethoscope.start_recording = function(option){
            console.log(option)
            $("#recordModal").modal('hide');
            spStart= new Spinner(opts).spin();
            starting_tracking.appendChild(spStart.el);
            //get only the second parameter in the time array. (linux timestamp).
            for (opt in option){
                for(arg in option[opt].arguments){
                    if(option[opt].arguments[arg][0] instanceof Date ){
                        option[opt].arguments[arg]=option[opt].arguments[arg][1];
                    }
                }
            }

            $http.post('/device/'+device_id+'/controls/start_record', data=option)
                 .success(function(data){$scope.device.status = data.status;});
            $http.get('/devices').success(function(data){
                    $http.get('/device/'+device_id+'/data').success(function(data){
                        $scope.device = data;
                    });
                 $("#recordModal").modal('hide');
            });
        };

        $scope.ethoscope.stop = function(){
            console.log("stopping")
            $http.post('/device/'+device_id+'/controls/stop', data={})
            .success(function(data){
                $scope.device.status = data.status;
            });
        };

        $scope.ethoscope.download = function(){
            $http.get($scope.device.ip+':9000/static'+$scope.result_files);
        };

        $scope.ethoscope.log = function(){
            var log_file_path = ''
            if ($scope.showLog == false){
                log_file_path = $scope.device.log_file;
                $http.post('/device/'+device_id+'/log', data={"file_path":log_file_path})
                     .success(function(data, status, headers, config){
                        $scope.log = data;
                        $scope.showLog = true;
                     });
            }else{
                $scope.showLog = false;
            }
        };

        $scope.ethoscope.poweroff = function(){
                //window.alert("Powering off... This tab will close when your device is turned off.")
                $http.post('/device/'+device_id+'/controls/poweroff', data={})
                     .success(function(data){
                        $scope.device= data;
                        window.close()
                })

        };

        $scope.ethoscope.alert= function(message){alert(message);};

        $scope.ethoscope.elapsedtime = function(t){
            // Calculate the number of days left
            var days=Math.floor(t / 86400);
            // After deducting the days calculate the number of hours left
            var hours = Math.floor((t - (days * 86400 ))/3600)
            // After days and hours , how many minutes are left
            var minutes = Math.floor((t - (days * 86400 ) - (hours *3600 ))/60)
            // Finally how many seconds left after removing days, hours and minutes.
            var secs = Math.floor((t - (days * 86400 ) - (hours *3600 ) - (minutes*60)))

            if (days>0){
                var x =  days + " days, " + hours + "h, " + minutes + "min,  " + secs + "s ";
            }else if ( days==0 && hours>0){
                var x =   hours + "h, " + minutes + "min,  " + secs + "s ";
            }else if(days==0 && hours==0 && minutes>0){
                var x =  minutes + "min,  " + secs + "s ";
            }else if(days==0 && hours==0 && minutes==0 && secs > 0){
                var x =  secs + " s ";
            }
            return x;

        };
        $scope.ethoscope.readable_url = function(url){
                //start tooltips
            $('[data-toggle="tooltip"]').tooltip()
                readable = url.split("/");
                len = readable.length;
                readable = ".../"+readable[len - 1];
                return readable;
        };
         $scope.ethoscope.start_date_time = function(unix_timestamp){
            var date = new Date(unix_timestamp*1000);
            return date.toUTCString();
        };

        var refresh = function(){
            $http.get('/device/'+device_id+'/data')
             .success(function(data){
                $scope.device= data;
                $scope.node_datetime = "TODO"
                $scope.device_datetime = "TODO"
                if("current_timestamp" in data){
                    $scope.device_timestamp = new Date(data.current_timestamp*1000);
                    $scope.device_datetime = $scope.device_timestamp.toUTCString();
                    $http.get('/node/timestamp').success(function(data_node){
                        node_t = data_node.timestamp;
                        node_time = new Date(node_t*1000);
                        $scope.node_datetime = node_time.toUTCString();
                        $scope.delta_t_min = (node_t - data.current_timestamp) / 60;
                     });
                }
                $scope.device.url_img = "/device/"+ $scope.device.id  + "/last_img" + '?' + Math.floor(new Date().getTime()/1000.0);
//                    $scope.device.ip = device_ip;
                status = $scope.device.status
                if (typeof spStart != undefined){
                    if(status != 'initialising' && status !='stopping'){
                        spStart.stop();
                    }
                }
             });
        }

        refresh_data = $interval(refresh, 3000);
        //clear interval when scope is destroyed
        $scope.$on("$destroy", function(){
        $interval.cancel(refresh_data);
        //clearInterval(refresh_data);
    });

    });

})()
