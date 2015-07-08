(function(){
    var moreController = function($scope, $http, $timeout, $routeParams){

        $scope.selected = {'files':[]};
        $scope.selected_all = false;
        $scope.showOptions = true;
        $scope.options = [{name:"Browse / Download Files",
                            icon:"fa fa-folder-open-o",
                            color:"alert alert-info",
                            opt: "browse"
                            },
                          {name:"Update System",
                           icon:"fa fa-refresh",
                           color:"alert alert-warning",
                           opt:"update",
                          },
                          {name:"Manage Node",
                           icon:"fa fa-cog",
                           color:"alert alert-success",
                           opt:"nodeManage",
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
                case "update":
                    $scope.check_update();
                    break;
                case "nodeManage":
                    get_node_info();
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
                console.log($scope.filesObj);
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
                var loadingContainer = document.getElementById('loading_devices');
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

/// Updates - Functions
        $scope.devices_to_update_selected = [];

        $scope.check_update = function(){
            //check if there is a new version
            $scope.update={};
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


            })
        };
        $scope.update_selected = function(devices_to_update){
            console.log(devices_to_update);
            if (devices_to_update == 'all'){
                devices_to_update=[]
                for (key in $scope.attached_devices){
                    devices_to_update.push($scope.attached_devices[key]);
                }
            }
            $http.post('/update', data = devices_to_update)
                 .success(function(data){
                    if (data.error){
                        $scope.update.error = data.error;
                    }
                    $scope.update_result= data;
                    $scope.update_waiting = true;
                    $timeout($scope.check_update, 15000);
                    $timeout(function(){$scope.update_waiting = false;}, 15000);
            })
        };
         $scope.update_node = function(node){
            $http.post('/update', data =node);
            $('#updateNodeModal').modal('hide');
            $scope.update_result= data;
            $scope.update_waiting = true;
            $timeout($scope.check_update, 15000);
            $timeout(function(){$scope.update_waiting = false;}, 15000);
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


    }

 angular.module('flyApp').controller('moreController',moreController);
})()
