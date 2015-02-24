(function(){
    var moreController = function($scope, $http){
        $scope.selected = {'files':[]};
        $scope.selected_all = false;
        $scope.showOptions = true;
        $scope.options = [{name:"Browse Files",
                            icon:"fa fa-refresh",
                            color:"alert alert-info",
                            opt: "browse"
                    }];
        $scope.exec_option = function(opt){
            if(opt == "browse"){
                $scope.browse();
            }
        }
        $scope.browse=function(folder="/null"){
            var prev_folder= folder.split("/");
            prev_folder.pop();
            $scope.prev_dir = prev_folder.join('/');
            console.log(folder);
            console.log(prev_folder);
            console.log($scope.prev_dir);
            $http.get("/browse"+folder)
                     .success(function(res){
                                console.log(res);
                        $scope.showFiles =  true;
                        $scope.files = res;
                     })
        };
        $scope.browse.dowload = function(){
            if($scope.selected.files.length == 1){
                console.log($scope.selected.files[0].name);
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
                console.log($scope.selected.files);
            }
        };


    }
    angular.module('flyApp').controller('moreController',moreController);
})()
