function maxLengthCheck(object) {
    if (object.value.length > object.maxLength)
        object.value = object.value.slice(0, object.maxLength)
}

(function(){
    var moreController = function($scope, $http, $timeout, $routeParams, $window){

        $scope.folders = {};
        $scope.users = {};
        $scope.incubators = {};
        $scope.sensors = {};
        
        $scope.phoneNumbr = /^\+((?:9[679]|8[035789]|6[789]|5[90]|42|3[578]|2[1-689])|9[0-58]|8[1246]|6[0-6]|5[1-8]|4[013-9]|3[0-469]|2[70]|7|1)(?:\W*\d){0,13}\d$/;

        $scope.selected = { 'files': [],
                            'folders' : {},
                            'users' : {},
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
                           color:"alert alert-success",
                           style:"font-size:36px; padding:10px",
                           opt: "nodeManage",
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
                    admin();
                    break;
                case "all":
                    break;
            };
        };
        
        console.log($routeParams.option);
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
                     .success(function(res){
                        filesObj =[];
                        for (key in res.files){
                            path = res.files[key].abs_path.split('/');
                            length = path.length;
                            size = bytesToSize(res.files[key].size)
                            file = {'device_id':path[length-4],
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
        $scope.browse.dowload = function(){

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
                     .success(function(res){
                         $scope.browse.download_url = '/download'+res.url;
                         spinner.stop();
                         $scope.selected = {'files':[]};
                         $('#downloadModal').modal('show');

                     })
            }
        };
        $scope.browse.remove_files = function(){
            $http.post('/remove_files', data=$scope.selected)
                 .success(function(res){
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
        
        bytesToSize = function (bytes) {
           if(bytes == 0) return '0 Byte';
           var k = 1000;
           var sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB', 'ZB', 'YB'];
           var i = Math.floor(Math.log(bytes) / Math.log(k));
           return (bytes / Math.pow(k, i)).toPrecision(3) + ' ' + sizes[i];
}

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
               $http.post('/node-actions', data = {'action': action})
               .success(function(res){
                $scope.nodeManagement[action]=res;
               });
        };

        $scope.nodeManagement.toggleDaemon = function(daemon_name, status){
            var spinner= new Spinner(opts).spin();
            $http.post('/node-actions', data = {'action': 'toggledaemon', 'daemon_name': daemon_name, 'status': status} )
                .success(function(data){
                    //$scope.daemons = data;
            });
            spinner.stop();
        };

        $scope.nodeManagement.saveFolders = function(){
            var spinner= new Spinner(opts).spin();
            $http.post('/node-actions', data = {'action': 'updatefolders', 'folders' : $scope.folders} )
                .success(function(data){
                    $scope.folders = data;
            });
            spinner.stop();
        };


        $scope.nodeManagement.adduser = function(){
            var spinner = new Spinner(opts).spin();
            $http.post('/node-actions', data = {'action': 'adduser', 'userdata' : $scope.selected['users']} )
                .success(function(data){
                    if ( data['result'] == 'success' ) { $scope.users = data['data'] };
            });
            spinner.stop();
        };

        $scope.nodeManagement.createUsername = function(){
            if($scope.selected['users'].fullname != '') {
                 var username = $scope.selected['users'].fullname.split(' ')[0].substr(0,1) + $scope.selected['users'].fullname.split(' ')[1].substr(0,49);
                 username = username.replace(/\s+/g, '');
                 username = username.replace(/\'+/g, '');
                 username = username.replace(/-+/g, '');
                 username = username.toLowerCase();
                 $scope.selected['users'].name = username;}
        };


        $scope.nodeManagement.loadData = function (type) {
            $scope.selected[type] = $scope[type][$scope.selected[type].name];
            console.log($scope.selected[type]);
        };


        $scope.nodeManagement.addincubator = function(){
            var spinner = new Spinner(opts).spin();
            $http.post('/node-actions', data = {'action': 'addincubator', 'incubatordata' : $scope.selected['incubators']} )
                .success(function(data){
                    if ( data['result'] == 'success' ) { $scope.incubators = data['data'] };
            });
            spinner.stop();
        };

        $scope.nodeManagement.addsensor = function(){
            var spinner = new Spinner(opts).spin();
            $http.post('/node-actions', data = {'action': 'addsensor', 'sensordata' : $scope.selected['sensors']} )
                .success(function(data){
                    if ( data['result'] == 'success' ) { $scope.sensors = data['data'] };
            });
            spinner.stop();
        };

///  View Server Logs
        var viewLog = function(){
            ///var log_file_path = $scope.device.log_file;
                $http.get('/node/log')
                     .success(function(data, status, headers, config){
                        $scope.log = data;
                        $scope.showLog = true;
                     });
        };
        
///  Admin
        var admin = function(){
            ///var log_file_path = $scope.device.log_file;
            $http.get('/node/daemons')
                 .success(function(data, status, headers, config){
                    $scope.daemons = data;
            });

            $http.get('/node/folders')
                 .success(function(data, status, headers, config){
                    $scope.folders = data;
                    $scope.selected['folders'] = data;
            });

            $http.get('/node/users')
                 .success(function(data, status, headers, config){
                    $scope.users = data;
            });

            $http.get('/node/incubators')
                 .success(function(data, status, headers, config){
                    $scope.incubators = data;
            });

            $http.get('/node/sensors')
                 .success(function(data, status, headers, config){
                    $scope.sensors = data;
            });
        
        };
        
}

 angular.module('flyApp').controller('moreController',moreController);

})()
