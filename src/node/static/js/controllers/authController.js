/**
 * Authentication Controller for Ethoscope Node
 * 
 * Handles login form and authentication UI.
 */
(function() {
    'use strict';

    angular.module('flyApp').controller('authController', function($scope, $location, AuthService, $timeout) {
        
        // Initialize scope variables
        $scope.loginForm = {
            username: '',
            pin: '',
            isSubmitting: false
        };
        
        $scope.changePinForm = {
            currentPin: '',
            newPin: '',
            confirmPin: '',
            isSubmitting: false
        };
        
        $scope.loginError = '';
        $scope.changePinError = '';
        $scope.changePinSuccess = '';
        $scope.showChangePinForm = false;
        
        // Get current user from AuthService
        $scope.currentUser = AuthService.getCurrentUser();
        $scope.isAuthenticated = AuthService.isAuthenticated;
        
        /**
         * Handle login form submission
         */
        $scope.submitLogin = function() {
            if ($scope.loginForm.isSubmitting) {
                return;
            }
            
            // Clear previous errors
            $scope.loginError = '';
            
            // Validate form
            if (!$scope.loginForm.username || !$scope.loginForm.pin) {
                $scope.loginError = 'Please enter both username and PIN';
                return;
            }
            
            $scope.loginForm.isSubmitting = true;
            
            AuthService.login($scope.loginForm.username, $scope.loginForm.pin)
                .then(function(result) {
                    $scope.loginForm.isSubmitting = false;
                    
                    if (result.success) {
                        // Login successful, ensure auth state is updated
                        console.log('Login successful, updating authentication state');
                        
                        // Force an authentication check to update the state
                        AuthService.checkAuthenticationStatus().then(function(isAuth) {
                            console.log('Auth state after login:', isAuth);
                            // Redirect to home
                            $location.path('/');
                        });
                    } else {
                        // Show error message
                        $scope.loginError = result.message;
                        
                        // Clear PIN field for security
                        $scope.loginForm.pin = '';
                        
                        // Focus back to PIN input after error
                        $timeout(function() {
                            var pinInput = document.getElementById('loginPin');
                            if (pinInput) {
                                pinInput.focus();
                            }
                        }, 100);
                    }
                })
                .catch(function(error) {
                    $scope.loginForm.isSubmitting = false;
                    $scope.loginError = 'Login failed due to connection error';
                    $scope.loginForm.pin = '';
                });
        };
        
        /**
         * Handle logout
         */
        $scope.logout = function() {
            AuthService.logout().then(function() {
                $location.path('/login');
            });
        };
        
        /**
         * Show change PIN form
         */
        $scope.showChangePin = function() {
            $scope.showChangePinForm = true;
            $scope.changePinError = '';
            $scope.changePinSuccess = '';
            
            // Clear form
            $scope.changePinForm = {
                currentPin: '',
                newPin: '',
                confirmPin: '',
                isSubmitting: false
            };
        };
        
        /**
         * Hide change PIN form
         */
        $scope.hideChangePin = function() {
            $scope.showChangePinForm = false;
            $scope.changePinError = '';
            $scope.changePinSuccess = '';
        };
        
        /**
         * Handle change PIN form submission
         */
        $scope.submitChangePin = function() {
            if ($scope.changePinForm.isSubmitting) {
                return;
            }
            
            // Clear previous messages
            $scope.changePinError = '';
            $scope.changePinSuccess = '';
            
            // Validate form
            if (!$scope.changePinForm.currentPin || !$scope.changePinForm.newPin || !$scope.changePinForm.confirmPin) {
                $scope.changePinError = 'All fields are required';
                return;
            }
            
            if ($scope.changePinForm.newPin !== $scope.changePinForm.confirmPin) {
                $scope.changePinError = 'New PIN confirmation does not match';
                return;
            }
            
            if ($scope.changePinForm.newPin === $scope.changePinForm.currentPin) {
                $scope.changePinError = 'New PIN must be different from current PIN';
                return;
            }
            
            $scope.changePinForm.isSubmitting = true;
            
            AuthService.changePin(
                $scope.changePinForm.currentPin,
                $scope.changePinForm.newPin,
                $scope.changePinForm.confirmPin
            )
            .then(function(result) {
                $scope.changePinForm.isSubmitting = false;
                
                if (result.success) {
                    $scope.changePinSuccess = result.message;
                    
                    // Clear form on success
                    $scope.changePinForm = {
                        currentPin: '',
                        newPin: '',
                        confirmPin: '',
                        isSubmitting: false
                    };
                    
                    // Hide form after 3 seconds
                    $timeout(function() {
                        $scope.hideChangePin();
                    }, 3000);
                } else {
                    $scope.changePinError = result.message;
                    
                    // Clear PIN fields for security
                    $scope.changePinForm.currentPin = '';
                    $scope.changePinForm.newPin = '';
                    $scope.changePinForm.confirmPin = '';
                }
            })
            .catch(function(error) {
                $scope.changePinForm.isSubmitting = false;
                $scope.changePinError = 'PIN change failed due to connection error';
                
                // Clear all fields
                $scope.changePinForm = {
                    currentPin: '',
                    newPin: '',
                    confirmPin: '',
                    isSubmitting: false
                };
            });
        };
        
        /**
         * Handle enter key press on login form
         */
        $scope.onLoginEnter = function($event) {
            if ($event.which === 13) { // Enter key
                $scope.submitLogin();
            }
        };
        
        /**
         * Handle enter key press on change PIN form
         */
        $scope.onChangePinEnter = function($event) {
            if ($event.which === 13) { // Enter key
                $scope.submitChangePin();
            }
        };
        
        // Listen for change PIN modal trigger from header
        $scope.$on('showChangePinModal', function() {
            $scope.showChangePin();
        });

        // Initialize focus on username field when controller loads
        $timeout(function() {
            var usernameInput = document.getElementById('loginUsername');
            if (usernameInput) {
                usernameInput.focus();
            }
        }, 100);
    });

})();