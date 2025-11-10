function maxLengthCheck(object) {
    if (object.value.length > object.maxLength)
        object.value = object.value.slice(0, object.maxLength)
}

(function(){
    var usersController = function($scope, $http, $timeout){

        // Initialize scope variables
        $scope.users = {};
        $scope.groups = [];
        $scope.selectedUser = {};
        $scope.userToDelete = {};
        $scope.searchText = '';
        $scope.showAll = false; // By default, show only active users
        $scope.sortType = 'fullname'; // Match home.html naming
        $scope.sortReverse = false;

        // Phone number validation pattern
        $scope.phonePattern = /^\+((?:9[679]|8[035789]|6[789]|5[90]|42|3[578]|2[1-689])|9[0-58]|8[1246]|6[0-6]|5[1-8]|4[013-9]|3[0-469]|2[70]|7|1)(?:\W*\d){0,13}\d$/;

        // Custom filter function for users (similar to home.html pattern)
        $scope.userFilter = function(users, searchText, showAll) {
            if (!users) return [];

            var filteredUsers = [];

            // Convert users object to array for easier filtering
            for (var key in users) {
                var user = users[key];
                user.key = key; // Store the key for reference

                // If showAll is false, only show active users
                if (!showAll && !user.active) {
                    continue;
                }

                filteredUsers.push(user);
            }

            // Apply search filter
            if (searchText) {
                filteredUsers = filteredUsers.filter(function(user) {
                    var searchLower = searchText.toLowerCase();
                    return (user.fullname && user.fullname.toLowerCase().indexOf(searchLower) !== -1) ||
                           (user.name && user.name.toLowerCase().indexOf(searchLower) !== -1) ||
                           (user.email && user.email.toLowerCase().indexOf(searchLower) !== -1) ||
                           (user.group && user.group.toLowerCase().indexOf(searchLower) !== -1) ||
                           (user.telephone && user.telephone.toLowerCase().indexOf(searchLower) !== -1);
                });
            }

            return filteredUsers;
        };

        // Load users and groups data
        var loadUsersData = function() {
            $http.get('/node/users')
                .then(function(response) {
                    var data = response.data;
                    $scope.users = data;

                    // Extract unique groups
                    $scope.groups = [];
                    for (var user in $scope.users) {
                        var userGroup = $scope.users[user]['group'];
                        if (userGroup && userGroup !== "" && !$scope.groups.includes(userGroup)) {
                            $scope.groups.push(userGroup);
                        }
                    }
                })
                .catch(function(error) {
                    console.error('Error loading users:', error);
                });
        };

        // Sort functionality (matching home.html pattern)
        // Note: sortBy function is not needed since we're using the home.html pattern
        // where sorting is handled directly in the ng-click

        // Clear selected user (for add new user)
        $scope.clearSelectedUser = function() {
            $scope.selectedUser = {
                active: true,
                isAdmin: false
            };
            console.log('Clear user - selectedUser:', $scope.selectedUser);
        };

        // Edit user
        $scope.editUser = function(user) {
            $scope.selectedUser = angular.copy(user);
            // Ensure we have an id property for edit mode detection
            if (!$scope.selectedUser.id && $scope.selectedUser.key) {
                $scope.selectedUser.id = $scope.selectedUser.key;
            }
            console.log('Edit user - selectedUser:', $scope.selectedUser);
        };

        // Create username from full name
        $scope.createUsername = function() {
            if ($scope.selectedUser.fullname && $scope.selectedUser.fullname !== '') {
                // Create username from full name (lowercase, replace spaces with dots)
                var username = $scope.selectedUser.fullname.toLowerCase()
                    .replace(/[^a-z\s]/g, '') // Remove non-alphabetic characters except spaces
                    .replace(/\s+/g, '.') // Replace spaces with dots
                    .replace(/\.+/g, '.') // Replace multiple dots with single dot
                    .replace(/^\.|\.$/g, ''); // Remove leading/trailing dots

                $scope.selectedUser.name = username;
            }
        };

        // Save user (add or update)
        $scope.saveUser = function() {
            var spinner = new Spinner(opts).spin();
            var loadingContainer = document.querySelector('.modal-body');
            if (loadingContainer) {
                loadingContainer.appendChild(spinner.el);
            }

            $http.post('/node-actions', {
                action: 'adduser',
                userdata: $scope.selectedUser
            })
            .then(function(response) {
                var data = response.data;
                if (data.result === 'success') {
                    $scope.users = data.data;
                    $scope.clearSelectedUser();

                    // Update groups list
                    $scope.groups = [];
                    for (var user in $scope.users) {
                        var userGroup = $scope.users[user]['group'];
                        if (userGroup && userGroup !== "" && !$scope.groups.includes(userGroup)) {
                            $scope.groups.push(userGroup);
                        }
                    }
                } else {
                    alert('Error saving user: ' + (data.message || 'Unknown error'));
                }
            })
            .catch(function(error) {
                console.error('Error saving user:', error);
                alert('Error saving user. Please try again.');
            })
            .finally(function() {
                if (spinner) {
                    spinner.stop();
                }
            });
        };

        // Toggle user active status (used in modal)
        $scope.toggleUserStatus = function(user) {
            var updatedUser = angular.copy(user);
            updatedUser.active = !updatedUser.active;

            $http.post('/node-actions', {
                action: 'adduser',
                userdata: updatedUser
            })
            .then(function(response) {
                var data = response.data;
                if (data.result === 'success') {
                    $scope.users = data.data;
                } else {
                    alert('Error updating user status: ' + (data.message || 'Unknown error'));
                }
            })
            .catch(function(error) {
                console.error('Error updating user status:', error);
                alert('Error updating user status. Please try again.');
            });
        };

        // Confirm delete user
        $scope.confirmDeleteUser = function(user) {
            $scope.userToDelete = user;
            $('#deleteUserModal').modal('show');
        };

        // Delete user
        $scope.deleteUser = function() {
            // Note: This functionality would need to be implemented in the backend
            // For now, we'll show a message that this feature is not yet implemented
            alert('Delete functionality is not yet implemented in the backend. Please contact the system administrator.');

            // When backend is ready, uncomment and modify this:
            /*
            $http.post('/node-actions', {
                action: 'deleteuser',
                userdata: $scope.userToDelete
            })
            .then(function(response) {
                var data = response.data;
                if (data.result === 'success') {
                    $scope.users = data.data;
                    $scope.userToDelete = {};
                } else {
                    alert('Error deleting user: ' + (data.message || 'Unknown error'));
                }
            })
            .catch(function(error) {
                console.error('Error deleting user:', error);
                alert('Error deleting user. Please try again.');
            });
            */
        };

        // Initialize data on controller load
        $scope.$on('$viewContentLoaded', function() {
            loadUsersData();
        });

        // Modal event handlers to ensure proper state management
        $('#addUserModal').on('show.bs.modal', function(e) {
            // Check if we're editing a user (button has data-user attribute) or adding new
            var button = $(e.relatedTarget);
            var isEditMode = button.hasClass('edit-user-btn');

            if (!isEditMode) {
                // This is for adding a new user
                $scope.clearSelectedUser();
                $scope.$apply();
            }
            // For edit mode, editUser() should have already been called
        });

        // Reset modal state when hidden
        $('#addUserModal').on('hidden.bs.modal', function() {
            $scope.selectedUser = {};
            $scope.$apply();
        });

        // Refresh data periodically (every 30 seconds)
        var refreshInterval = setInterval(function() {
            if (document.visibilityState === "visible") {
                loadUsersData();
            }
        }, 30000);

        // Clean up interval on scope destroy
        $scope.$on("$destroy", function() {
            if (refreshInterval) {
                clearInterval(refreshInterval);
            }
        });
    };

    angular.module('flyApp').controller('usersController', usersController);
})();
