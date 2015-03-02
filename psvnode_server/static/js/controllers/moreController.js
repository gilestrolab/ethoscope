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
                          }
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
        }
        $scope.browse=function(folder="/null"){
            var prev_folder= folder.split("/");
            prev_folder.pop();
            $scope.prev_dir = prev_folder.join('/');
            $http.get("/browse"+folder)
                     .success(function(res){
                                console.log(res);
                        $scope.files = res;
                     })
        };
        $scope.browse.dowload = function(){
            if($scope.selected.files.length == 1){
                $http.get('/static/'+$scope.selected.files.name);
            }
        };
        $scope.browse.toggleAll = function(){
            if($scope.selected_all == false){
                $scope.selected.files = angular.copy($scope.files.files);
                $scope.selected_all = true;
                console.log($scope.selected.files);
            }else {
                $scope.selected.files = [];
                $scope.selected_all = false;
            }
        };

        $scope.check_update = function(){
            //check if there is a new version
            $http.get("/update/check")
                 .success(function(res){
                    if (Object.keys(res).length == 0){
                        $scope.update_text = "All the connected devices and Node are update to the latest version. Well Done!";
                        $scope.update_need_update = false;
                        $scope.devices_to_update={};

                    }else{
                        $scope.update_text = "There is a new version and some devices need to be updated";
                        $scope.update_need_update = true;
                        $scope.devices_to_update=res;
                        for (dev in res){
                            if (dev.status != 'stopped'){
                                $scope.started == true;
                                break;
                            }
                        }
                    }
                    console.log(res);
            })
            //$http.post("/update", data = data)
        };
        $scope.update_selected = function(devices_to_update){
            console.log(devices_to_update);
            $http.post('/update', data = devices_to_update)
                 .success(function(data){
                    $scope.update_result= data;
                    $scope.update_waiting = true;
                    $timeout($scope.check_update, 6000);
                    $timeout(function(){$scope.update_waiting = false;}, 6000);
            })
        };


    }
    angular.module('flyApp').controller('moreController',moreController);
})()
