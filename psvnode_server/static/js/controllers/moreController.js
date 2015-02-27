(function(){
    var moreController = function($scope, $http){
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
                    $scope.browse();
                case "update":
                    $scope.update();
            };
            if(opt == "browse"){
                $scope.browse();
            }
        }
        $scope.browse=function(folder="/null"){
            var prev_folder= folder.split("/");
            prev_folder.pop();
            $scope.prev_dir = prev_folder.join('/');
            $http.get("/browse"+folder)
                     .success(function(res){
                                console.log(res);
                        $scope.showFiles =  true;
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

        $scope.update = function(){
            //check if there is a new version
            $http.get("/update/check")
                 .success(function(res){
                    $scope.showUpdates = true;
                    $scope.update.text = res;
                    console.log(res);
            })
            //$http.post("/update", data = data)
        };


    }
    angular.module('flyApp').controller('moreController',moreController);
})()
