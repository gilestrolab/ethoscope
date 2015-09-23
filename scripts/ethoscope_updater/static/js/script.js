(function(){
    var app = angular.module('updater', ['ngRoute']);
    app.filter("toArray", function(){
        return function(obj) {
            var result = [];
            angular.forEach(obj, function(val, key) {
                result.push(val);
            });
            return result;
        };
    });
    
    // create the controller and inject Angular's $scope
    app.controller('mainController', function($scope, $http, $interval, $timeout) {
        $scope.system = {};
        $scope.system.isUpdated = false;
        $scope.node ={};
        $scope.devices={};
        $scope.groupActions={};
        var spinner= new Spinner(opts).spin();
        var loadingContainer = document.getElementById('loading_devices');
        loadingContainer.appendChild(spinner.el);
        $scope.spinner_text = 'Fetching, please wait...';
        $http.get('/bare/update').success(function(data){
            console.log(data);
            if ('error' in data){
                $scope.system.error= data.error;
                console.log($scope.system.isUpdated);
            }else{
                $scope.system.isUpdated = true;
                $scope.system.status = data;
                console.log($scope.system.isUpdated);
            }
            spinner.stop();
            $scope.spinner = false;
            $scope.spinner_text = null;

        });
        $http.get('/devices').success(function(data){
            console.log(data);
            $scope.devices = data;
        });
        $http.get('/device/check_update').success(function(data){
            console.log(data);
            $scope.node.check_update = data;
        });
        $http.get('/device/active_branch').success(function(data){
            console.log(data);
            $scope.node.active_branch = data.active_branch;
        });
        
        //Scan for SM or SD connected.
        $scope.get_devices = function(){
            var spinner= new Spinner(opts).spin();
            var loadingContainer = document.getElementById('loading_devices');
            try {
                loadingContainer.appendChild(spinner.el);
            }
            catch(err) {
                console.log("no container");
            }
            $http.get('/devices').success(function(data){
                $scope.devices = data;
                spinner.stop();
                $scope.loading_devices = false;
            })
        };
        $scope.secToDate = function(secs){
            d = new Date(secs*1000);
            return d.toString();
        };
        $scope.elapsedtime = function(t){
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
        
        $scope.groupActions.checkStart = function(selected_devices){
            softwareVersion = ""; 
            device_version = "";
            checkVersionLoop: 
            for (var i = 0; i< selected_devices.length(); i++){
                    $http.get('/device/'+selected_devices[i]+'/data').success(function(data){device_version = data.version.id});
                    if (i == 0) {
                        softwareVersion = device_version;
                    }
                    if (softwareVersion != device_version){
                        break checkVersionLoop;
                    }
            }
        };
                   
        $scope.groupActions.start = function(){
                            $("#startModal").modal('hide');
                            spStart= new Spinner(opts).spin();
                            starting_tracking.appendChild(spStart.el);
                            $http.post('/device/'+device_id+'/controls/start', data=option)
                                 .success(function(data){$scope.device.status = data.status;});
             $http.get('/devices').success(function(data){
                    $http.get('/device/'+device_id+'/data').success(function(data){
                        $scope.device = data;

                    });

                    $http.get('/device/'+device_id+'/ip').success(function(data){
                        $scope.device.ip = data;
                        device_ip = data;
                    });
                 $("#startModal").modal('hide');
            });
        };
        
        /// Updates - Functions
        $scope.devices_to_update_selected = [];

        $scope.check_update = function(){
            //check if there is a new version
            $scope.update={};
            var spinner= new Spinner(opts).spin();
            var loadingContainer = document.getElementById('loading');
            loadingContainer.appendChild(spinner.el);
            $http.get("/update/check")
                 .success(function(res){
                    if(res.update.error){
                        if(res.update.error.indexOf('up to date')<0){
                            $scope.update.error = res.update.error;
                        }
                    }
                    for (dev in res.attached_devices){
                        if (dev.version != res.origin.version){
                            $scope.update_text = "There is a new version and some devices need to be updated";
                            break;
                        }
                    }

                    $scope.attached_devices=res.attached_devices;
                    $scope.origin = res.origin;
                    $scope.node = res.update.node;
                    $('#updateDevicesModal').modal('hide');
                    spinner.stop();
            })
        };
        $scope.update_selected = function(devices_to_update){
            if (devices_to_update == 'all'){
                devices_to_update=[]
                for (key in $scope.attached_devices){
                    devices_to_update.push($scope.attached_devices[key]);
                }
            }
            var spinner= new Spinner(opts).spin();
            var loadingContainer = document.getElementById('loading');
            loadingContainer.appendChild(spinner.el);
            $http.post('/update', data = devices_to_update)
                 .success(function(data){
                    if (data.error){
                        $scope.update.error = data.error;
                    }
                    $scope.update_result= data;
                    $scope.update_waiting = true;
                    $timeout($scope.check_update, 15000);
                    $timeout(function(){$scope.update_waiting = false;}, 15000);
                    $timeout(function(){spinner.stop();},15100);
            })
        };
         $scope.update_node = function(node){
            var spinner= new Spinner(opts).spin();
            var loadingContainer = document.getElementById('loading');
            loadingContainer.appendChild(spinner.el);
            $http.post('/update', data =node);
            $('#updateNodeModal').modal('hide');
            $scope.update_result= data;
            $scope.update_waiting = true;
            $timeout($scope.check_update, 15000);
            $timeout(function(){$scope.update_waiting = false;}, 15000);
            $timeout(function(){spinner.stop();},15100);

        };


/// Node Management update
        $scope.nodeManagement = {};
        var get_node_info = function(){
            $http.get('/node/info').success(function(res){
                $scope.nodeManagement.info = res;
            })
        }
        $scope.nodeManagement.time = new Date();
        $scope.nodeManagement.time = $scope.nodeManagement.time.toString();
        $scope.nodeManagement.action = function(action){
               $http.post('/node-actions', data = {'action':action})
               .success(function(res){
                $scope.nodeManagement[action]=res;
               });
        };

        //$scope.$on('$viewContentLoaded',$scope.get_devices);

    });

}
)()
