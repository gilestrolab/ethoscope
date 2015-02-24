(function(){
    var moreController = function($scope, $http){
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

    }
    angular.module('flyApp').controller('moreController',moreController);
})()
