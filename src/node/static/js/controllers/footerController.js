(function(){
    var footerController = function($scope, $http){

        $scope.gitInfo = {
            branch: 'loading...',
            commit: 'loading...',
            date: 'loading...'
        };

        var loadGitInfo = function(){
            $http.get('/node/info').then(function(response) {
                var res = response.data;
                $scope.gitInfo = {
                    branch: res.GIT_BRANCH || 'Unknown',
                    commit: res.GIT_COMMIT || 'Unknown',
                    date: res.GIT_DATE || 'Unknown'
                };
            }).catch(function() {
                $scope.gitInfo = {
                    branch: 'Error loading',
                    commit: 'Error loading',
                    date: 'Error loading'
                };
            });
        };

        // Load git info on controller initialization
        loadGitInfo();

    };

    angular.module('flyApp').controller('FooterController',
        ['$scope', '$http', footerController]);

})();
