(function(){
    var moreController = function($scope, $http, $timeout){
        $scope.selected = {'files':[]};
        $scope.selected_all = false;
        $scope.showOptions = true;
        $scope.options = [{name:"Browse Files",
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
            $scope.showOption =  opt;
            switch(opt){
                case "browse":
                    $scope.browse();
                case "update":
                    $scope.check_update();
                case "nodeManage":
                    get_node_info();

            };
        };

        ///Browse Functions

        /*$scope.browse_table = $('#browse_table').DataTable({
                            "paging": true,
                            "searching": true,
                            "order":[2,'desc'],
                            "dom": '<"col-xs-12"il<"right"f>><"col-xs-12"t><"right"p><"clear">',
                            "columns": [
                                    { "data": "device_name",
                                    render :function (data, type, full, meta) {
                                                    return '<td><a href="#/sm/'+full.device_id+'" target="_blank">'+full.device_name+'</a></td>'}},
                                    { "data": "exp_date",
                                      render:function(data, type, full, meta){
                                           return '<td>'+full.exp_date+'</td>'
                                        }
                                    },
                                    { "data":"file",
                                     render:function(data, type, full, meta){
                                     return '<td><a href="/download'+full.url+'"  target="_blank" >'+full.file+'</a></td>'
                                    }
                                    },
                                    { "data": null,
                                    render: function(data, type, full, meta){
                                     return '<td><center><input type="checkbox" ng-model="" value="'+full.url+'" ></center></td>'
                                                }},

                                ],

        });*/


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
                            file = {'device_id':path[length-4],
                                    'device_name':path[length-3],
                                    'exp_date':path[length-2],
                                    'file':path[length-1],
                                    'url':res.files[key].abs_path};
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
                $('#downloadModal').modal('show');
                $scope.browse.download_url ='';
                $http.post('/request_download/files', data=$scope.selected)
                     .success(function(res){
                        console.log(res);
                         $scope.browse.download_url = '/download'+res.url;
                     })
            }
        };
        $scope.browse.remove_files = function(){
            $http.post('/remove_files', data=$scope.selected)
                 .success(function(res){
                        console.log(res);
                        $('#deleteModal').modal('hide');
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

/// Updates - Functions
        $scope.devices_to_update_selected = {};

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

                    $scope.update_text = "There is a new version and some devices need to be updated";
                    $scope.attached_devices=res.attached_devices;
                    $scope.origin = res.origin;
                    $scope.node = res.update.node;
                    /*for (dev in res.attached_devices){
                        if (dev.status != 'stopped'){
                            $scope.started == true;
                            break;
                        }
                    }*/

            })
        };
        $scope.update_selected = function(devices_to_update){
            $http.post('/update', data = devices_to_update)
                 .success(function(data){
                    $scope.update_result= data;
                    $scope.update_waiting = true;
                    $timeout($scope.check_update, 15000);
                    $timeout(function(){$scope.update_waiting = false;}, 15000);
            })
        };
         $scope.update_node = function(node){
            $http.post('/update', data = {'node':node});
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
