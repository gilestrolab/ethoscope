(function(){
    var moreController = function($scope, $http, $timeout, $routeParams, $window){

        $scope.selected = {'files':[]};
        $scope.selected_all = false;
        $scope.showOptions = true;
        $scope.options = [{name:"Browse / Download Files",
                            icon:"fa fa-folder-open-o",
                            color:"alert alert-info",
                            opt: "browse"
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

}
 angular.module('flyApp').controller('moreController',moreController);
})()
