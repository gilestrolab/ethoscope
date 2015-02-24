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
                $http.get("/browse/all")
                     .success(function(res){
                                console.log(res);
                        $scope.showFiles =  true;
                        $scope.files = res;
                     })
            }
        }

    }
    angular.module('flyApp').controller('moreController',moreController);
})()
