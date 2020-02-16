(function(){
    var app = angular.module('flyApp', ['ngRoute', 'daterangepicker', 'angularUtils.directives.dirPagination']);
    
    app.filter("toArray", function(){
        return function(obj) {
            var result = [];
            angular.forEach(obj, function(val, key) {
                result.push(val);
            });
            return result;
        };
    });

    app.filter('orderObjectBy', function() {
      return function(items, field, reverse) {
        var filtered = [];
        angular.forEach(items, function(item) {
          filtered.push(item);
        });
        filtered.sort(function (a, b) {
          return (a[field] > b[field] ? 1 : -1);
        });
        if(reverse) filtered.reverse();
        return filtered;
      };
    });

    // configure our routes

    app.config(function($routeProvider, $locationProvider) {
        $routeProvider

            // route for the home page
            .when('/', {
                templateUrl : '/static/pages/home.html',
                controller  : 'mainController'
            })

            // route for the sleep monitor page
            .when('/ethoscope/:device_id', {
                templateUrl : '/static/pages/ethoscope.html',
                controller  : 'ethoscopeController'
            })

            // route for the management page
            .when('/more/:option', {
                templateUrl : '/static/pages/more.html',
                controller  : 'moreController',
            })

            // route for the experiments database page
            .when('/experiments', {
                templateUrl : '/static/pages/experiments.html',
                controller  : 'experimentsController',
            })

            // route for the experiments database page
            .when('/resources', {
                templateUrl : '/static/pages/resources.html',
                controller  : 'resourcesController',
            })


            // route for the help page
            /*.when('/help', {
                templateUrl : '/static/pages/help.html',
                controller  : 'helpController'
            })*/
        ;
        // use the HTML5 History API
        $locationProvider.html5Mode(true);
    });

    // create the controller and inject Angular's $scope
    app.controller('mainController', function($scope, $http, $interval, $timeout) {
        $scope.sortType = 'name'; // set the default sort type
        $scope.sortReverse = false;  // set the default sort order
        $scope.filterEthoscopes = '';     // set the default search/filter term
        
        $scope.groupActions = {};
//        $http.get('/node/time').success(function(data){
//            t = new Date(data.time);
//            $scope.time = t.toString();
//        });

        $http.get('/devices').success(function(data){
            $scope.devices = data;
        });

        $http.get('/sensors').success(function(data){
            $scope.sensors = data;
            $scope.has_sensors = Object.keys($scope.sensors).length;
        });
        

        var update_local_times = function(){
            $http.get('/node/time').success(function(data){
                t = new Date(data.time);
                $scope.time = t.toString();
                });
            var t = new Date();
            $scope.localtime = t.toString();
        };

        $scope.get_devices = function(){
            $http.get('/devices').success(function(data){

                data_list = [];

                for(d in data){
                    data_list.push(data[d]);
                    }

                $scope.devices = data_list;
                $scope.n_devices=$scope.devices.length;
                status_summary = {};

                for(d in $scope.devices){

                    dev = $scope.devices[d]

                    if(!(dev.status in status_summary))
                        status_summary[dev.status] = 0;
                     status_summary[dev.status] += 1;
                }


                $scope.status_n_summary = status_summary
            })
        };
        $scope.secToDate = function(secs){
            d = new Date (isNaN(secs) ? secs : secs * 1000 );

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

        $scope.$on('$viewContentLoaded',$scope.get_devices);


       var refresh_platform = function(){
            if (document.visibilityState=="visible"){
                    $scope.get_devices();
                    update_local_times();
                    //console.log("refresh platform", new Date());
            }
       };

       // refresh every 5 seconds
       refresh_data = $interval(refresh_platform, 5 * 1000);
        
        //clear interval when scope is destroyed
        $scope.$on("$destroy", function(){
            $interval.cancel(refresh_data);
            //clearInterval(refresh_data);
        });
    });
}
)()
