function maxLengthCheck(object) {
    if (object.value.length > object.maxLength)
        object.value = object.value.slice(0, object.maxLength)
}

(function(){
    var moreController = function($scope, $http, $timeout, $routeParams, $window, $location){

        var spin = function(action){
            if (action=="start"){
                     $scope.spinner= new Spinner(opts).spin();
                    var loadingContainer = document.getElementById('loading');
                    loadingContainer.appendChild($scope.spinner.el);
                }else if (action=="stop"){
                     $scope.spinner.stop();
                     $scope.spinner = false;
                }
            }

        $scope.folders = {};
        $scope.incubators = {};
        $scope.sensors = {};
        
        $scope.phoneNumbr = /^\+((?:9[679]|8[035789]|6[789]|5[90]|42|3[578]|2[1-689])|9[0-58]|8[1246]|6[0-6]|5[1-8]|4[013-9]|3[0-469]|2[70]|7|1)(?:\W*\d){0,13}\d$/;

        $scope.selected = { 'files': [],
                            'folders' : {},
                            'incubators' : {},
                            'sensors' : {}
                          };
                          
        $scope.selected_all = false;
        $scope.showOptions = true;
        $scope.options = [{name:"Browse / Download Files",
                            icon:"fa fa-folder-open",
                            color:"alert alert-info",
                            style:"font-size:36px; padding:10px",
                            opt: "browse"
                            },
                          {name:"Node information",
                           icon:"fa fa-info",
                           color:"alert alert-info",
                           style:"font-size:36px; padding:10px",
                           opt: "nodeInfo",
                           },
                          {name:"View Node Log",
                           icon:"fa fa-book",
                           color:"alert alert-info",
                           style:"font-size:36px; padding:10px",
                           opt: "viewLog",
                          },
                          {name:"Node Management",
                           icon:"fa fa-cog",
                           color:"alert alert-info",
                           style:"font-size:36px; padding:10px",
                           opt: "nodeManage",
                          },
                          {name:"Node Actions",
                           icon:"fa fa-terminal",
                           color:"alert alert-info",
                           style:"font-size:36px; padding:10px",
                           opt: "nodeCommands",
                          },
                          {name:"Setup Wizard",
                           icon:"fa fa-magic",
                           color:"alert alert-warning",
                           style:"font-size:36px; padding:10px",
                           opt: "setupWizard",
                          },

                         ];

        $scope.exec_option = function(opt){
            if (opt.name == '$viewContentLoaded'){
                opt = $routeParams.option;
            };
            $scope.showOption =  opt;
            switch(opt){
                case "browse":
                    $scope.browse();
                    break;
                case "nodeInfo":
                    get_node_info();
                    break;
                case "viewLog":
                    viewLog();
                    break;
                case "nodeManage":
                    getNodeConfiguration();
                    break;
                case "nodeCommands":
                    getNodeConfiguration();
                    break;
                case "setupWizard":
                    $location.path('/installation-wizard').search('reconfigure', 'true');
                    break;
                case "all":
                    break;
            };
        };
        
        if ($routeParams.option != 'undefined'){
        $scope.$on('$viewContentLoaded',$scope.exec_option);
        }
        ///Browse Functions


        $scope.browse=function(folder){
            folder = folder || "/null"
            var prev_folder= folder.split("/");
            prev_folder.pop();
            $scope.prev_dir = prev_folder.join('/');
            $http.get("/browse"+folder)
                     .then(function(response) { var res = response.data;
                        var filesObj =[];
                        for (var key in res.files){
                            var path = res.files[key].abs_path.split('/');
                            var length = path.length;
                            var size = bytesToSize(res.files[key].size)
                            var file = {'device_id':path[length-4],
                                    'device_name':path[length-3],
                                    'exp_date':path[length-2],
                                    'file':path[length-1],
                                    'url':res.files[key].abs_path,
                                    'size':size};

                            filesObj.push(file);
                        }
                        $scope.files = res;
                        $scope.filesObj = filesObj;
                        $scope.abs_path = res.absolute_path;
                //$scope.browse_table.clear();
                //$scope.browse_table.rows.add(filesObj).draw();
                //console.log($scope.filesObj);
                     })
        };
        $scope.browse.download = function(){

            if($scope.selected.files.length == 1){
                $('#downloadModal').modal('show');
                $scope.browse.download_url = '/download'+$scope.selected.files[0].name;
                $scope.browse.show_download_panel = true;
            }else{
                $scope.browse.download_url ='';
                var spinner= new Spinner(opts).spin();
                var loadingContainer = document.getElementById('loading');
                loadingContainer.appendChild(spinner.el);
                $http.post('/request_download/files', data=$scope.selected)
                     .then(function(response) { var res = response.data;
                         $scope.browse.download_url = '/download'+res.url;
                         spinner.stop();
                         $scope.selected = {'files':[]};
                         $('#downloadModal').modal('show');

                     })
            }
        };
        $scope.browse.remove_files = function(){
            $http.post('/remove_files', data=$scope.selected)
                 .then(function(response) { var res = response.data;
                        $('#deleteModal').modal('hide');
                        $scope.selected = {'files':[]};
                        $scope.exec_option('browse');
                 });
            };

        $scope.browse.toggleAll = function(){
            if($scope.selected_all == false){

                $scope.selected.files = angular.copy($scope.filesObj);
                $scope.selected_all = true;
                console.log($scope.selected);
            }else {
                $scope.selected.files = [];
                $scope.selected_all = false;
            }
        };
        
        var bytesToSize = function (bytes) {
           if(bytes == 0) return '0 Byte';
           var k = 1000;
           var sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB', 'ZB', 'YB'];
           var i = Math.floor(Math.log(bytes) / Math.log(k));
           return (bytes / Math.pow(k, i)).toPrecision(3) + ' ' + sizes[i];
}

/// Node Management update
        $scope.nodeManagement = {};
        
        var get_node_info = function(){
            $http.get('/node/info').then(function(response) { var res = response.data;
                $scope.nodeManagement.info = res;
            })
        }
        
        $scope.nodeManagement.time = new Date();
        $scope.nodeManagement.time = $scope.nodeManagement.time.toString();
        
        $scope.nodeManagement.exec_cmd = function(cmd_name){
            $http.post('/node-actions', data = {'action': 'exec_cmd', 'cmd_name' : cmd_name})
            .then(function(response) { var data = response.data;
                $scope.nodeManagement.std_output = data;
            });
        };
        
        $scope.nodeManagement.action = function(action){
               $http.post('/node-actions', data = {'action': action})
               .then(function(response) { var res = response.data;
                $scope.nodeManagement[action]=res;
               });
        };

        $scope.nodeManagement.toggleDaemon = function(daemon_name, status){
            var spinner= new Spinner(opts).spin();
            $http.post('/node-actions', data = {'action': 'toggledaemon', 'daemon_name': daemon_name, 'status': status} )
                .then(function(response) { var data = response.data;
                    //$scope.daemons = data;
            });
            spinner.stop();
        };

        $scope.nodeManagement.saveFolders = function(){
            var spinner= new Spinner(opts).spin();
            $http.post('/node-actions', data = {'action': 'updatefolders', 'folders' : $scope.folders} )
                .then(function(response) { var data = response.data;
                    $scope.folders = data;
            });
            spinner.stop();
        };




        $scope.nodeManagement.loadData = function (type) {
            $scope.selected[type] = $scope[type][$scope.selected[type].name];
        };


        $scope.nodeManagement.addincubator = function(){
            var spinner = new Spinner(opts).spin();
            $http.post('/node-actions', data = {'action': 'addincubator', 'incubatordata' : $scope.selected['incubators']} )
                .then(function(response) { var data = response.data;
                    if ( data['result'] == 'success' ) { $scope.incubators = data['data'] };
            });
            spinner.stop();
        };

        $scope.nodeManagement.addsensor = function(){
            var spinner = new Spinner(opts).spin();
            $http.post('/node-actions', data = {'action': 'addsensor', 'sensordata' : $scope.selected['sensors']} )
                .then(function(response) { var data = response.data;
                    if ( data['result'] == 'success' ) { $scope.sensors = data['data'] };
            });
            spinner.stop();
        };

///  View Server Logs
        var viewLog = function(){
            ///var log_file_path = $scope.device.log_file;
                spin('start');
                $http.get('/node/log')
                     .then(function(response) { var data = response.data;
                        $scope.log = data;
                        $scope.showLog = true;
                        spin('stop');
                     })
                      .catch(function(){
                        spin('stop');
                     });
        };
        
///  Admin configurations
        var getNodeConfiguration = function(){
            ///var log_file_path = $scope.device.log_file;
            $http.get('/node/daemons')
                 .then(function(response) { var data = response.data;
                    $scope.daemons = data;
            });

            $http.get('/node/folders')
                 .then(function(response) { var data = response.data;
                    $scope.folders = data;
                    $scope.selected['folders'] = data;
            });

            

            $http.get('/node/incubators')
                 .then(function(response) { var data = response.data;
                    $scope.incubators = data;
            });

            $http.get('/node/sensors')
                 .then(function(response) { var data = response.data;
                    $scope.sensors = data;
            });
        
            $http.get('/node/commands')
                 .then(function(response) { var data = response.data;
                    $scope.commands = data;
            });

        
        };

        
}

 angular.module('flyApp').controller('moreController', 
    ['$scope', '$http', '$timeout', '$routeParams', '$window', '$location', moreController]);

})()
