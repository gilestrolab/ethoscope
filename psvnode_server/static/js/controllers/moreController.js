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
                         ];
        $scope.exec_option = function(opt){
            switch(opt){
                case "browse":
                    $scope.showOption = opt;
                    $scope.browse();

                case "update":
                    $scope.showOption =  opt;
                    $scope.check_update();

            };
        };


        $scope.browse_table = $('#browse_table').DataTable({
                            "paging": true,
                            "searching": true,
                            "order":[2,'desc'],
                            "dom": '<"col-xs-12"<"right"f>><"col-xs-12"t><"right"p><"clear">',
                            "columns": [
                                    { "data": "device_name",
                                    render :function (data, type, full, meta) {
                                                    return '<td><a href="#/sm/'+full.device_id+'" target="_blank">'+data+'</a></td>'}},
                                    { "data": "exp_date",
                                      render:function(data, type, full, meta){
                                           return '<td>'+data+'</td>'
                                        }
                                    },
                                    { "data":"file",
                                     render:function(data, type, full, meta){
                                     return '<td><a href="/download'+full.url+'"  target="_blank">'+data+'</a></td>'
                                    }
                                    },
                                    { "data": null,
                                    render: function(data, type, full, meta){
                                     return '<td><input type="checkbox" checklist-model="selected.files" checklist-value="'+full.url+'"></td>'
                                                }},

                                ],

        });

// Browse - Functions
        $scope.browse=function(folder){
            folder = folder || "/null"
            var prev_folder= folder.split("/");
            prev_folder.pop();
            $scope.prev_dir = prev_folder.join('/');
            $http.get("/browse"+folder)
                     .success(function(res){
                        filesObj =[];
                        for (key in res.files){
                            //res.files[key].route_to_show =  res.files[key].name.split("/").slice(3).join("/");
                            path = res.files[key].abs_path.split('/');
                            file = {'device_id':path[-4],
                                    'device_name':path[-3],
                                    'exp_date':path[-2],
                                    'file':path[-1],
                                    'url':res.files[key].abs_path};
                            filesObj.push(file);
                        }
                        $scope.files = res;
                        $scope.filesObj = filesObj;
                        $scope.abs_path = res.absolute_path;
                console.log($scope.abs_path);

                $scope.browse_table.clear();
                $scope.browse_table.rows.add(filesObj).draw();
                     })
        };
        $scope.browse.dowload = function(){
            if($scope.selected.files.length == 1){
                console.log("files to download");
                console.log($scope.selected.files[0].name);
                $scope.browse.download_url = '/download'+$scope.selected.files[0].name;
                $scope.browse.show_download_panel = true;
            }else{
                console.log("files to download");
                console.log($scope.selected.files);
                $scope.browse.download_url ='';
                $http.post('/request_download/files', data=$scope.selected)
                     .success(function(res){
                        console.log(res);
                         $scope.browse.download_url = '/download'+res.url;
                     })
            }
        };
        $scope.browse.toggleAll = function(){
            if($scope.selected_all == false){
                $scope.selected.files = angular.copy($scope.files.files);
                $scope.selected_all = true;
            }else {
                $scope.selected.files = [];
                $scope.selected_all = false;
            }
        };

// Updates - Functions
        $scope.devices_to_update_selected = {};

        $scope.check_update = function(){
            //check if there is a new version
            $http.get("/update/check")
                 .success(function(res){
                    if(res.error){
                        $scope.attached_devices = {};
                        $scope.attached_devices.error = res.error;
                    }
                    if (Object.keys(res.attached_devices).length == 0){
                        $scope.update_text = "All connected devices and the Node are up to update. Well Done!";
                        $scope.update_need_update = false;
                        $scope.origin = res.origin;
                        $scope.node = res.update.node;
                        $scope.attached_devices={};

                    }else{
                        $scope.update_text = "There is a new version and some devices need to be updated";
                        $scope.update_need_update = true;
                        $scope.attached_devices=res.attached_devices;
                        $scope.origin = res.origin;
                        $scope.node = res.update.node;
                        for (dev in res.attached_devices){
                            if (dev.status != 'stopped'){
                                $scope.started == true;
                                break;
                            }
                        }
                    }
            })
            //$http.post("/update", data = data)
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


    }
    angular.module('flyApp').controller('moreController',moreController);
})()
