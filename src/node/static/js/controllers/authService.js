/**
 * Authentication Service for Ethoscope Node
 *
 * Handles user login, logout, session management, and authentication checks.
 */
(function() {
    'use strict';

    angular.module('flyApp').service('AuthService', function($http, $location, $timeout, $interval) {
        var self = this;

        // Current user data
        self.currentUser = null;
        self.isAuthenticated = false;
        self.isAdmin = false;

        // Session check interval
        var sessionCheckInterval = null;

        /**
         * Check if user is currently authenticated
         */
        self.checkAuthenticationStatus = function() {
            return $http.get('/auth/session')
                .then(function(response) {
                    if (response.data && response.data.authenticated) {
                        self.currentUser = response.data.user;
                        self.isAuthenticated = true;
                        self.isAdmin = response.data.user.isadmin || false;
                        return true;
                    } else {
                        self.clearSession();
                        return false;
                    }
                })
                .catch(function(error) {
                    console.log('Session check failed:', error);
                    self.clearSession();
                    return false;
                });
        };

        /**
         * Login with username and PIN
         */
        self.login = function(username, pin) {
            return $http.post('/auth/login', {
                username: username,
                pin: pin
            })
            .then(function(response) {
                if (response.data && response.data.success) {
                    self.currentUser = response.data.user;
                    self.isAuthenticated = true;
                    self.isAdmin = response.data.user.isadmin || false;

                    // Start session monitoring
                    self.startSessionMonitoring();

                    return {
                        success: true,
                        message: response.data.message,
                        user: response.data.user
                    };
                } else {
                    return {
                        success: false,
                        message: response.data.message || 'Login failed'
                    };
                }
            })
            .catch(function(error) {
                var message = 'Login failed due to server error';
                if (error.data && error.data.message) {
                    message = error.data.message;
                } else if (error.status === 401) {
                    message = 'Invalid username or PIN';
                } else if (error.status === 429) {
                    message = 'Too many login attempts. Please try again later.';
                }

                return {
                    success: false,
                    message: message
                };
            });
        };

        /**
         * Logout current user
         */
        self.logout = function() {
            return $http.post('/auth/logout')
                .then(function(response) {
                    self.clearSession();
                    $location.path('/login');
                    return {
                        success: true,
                        message: 'Logged out successfully'
                    };
                })
                .catch(function(error) {
                    // Even if logout request fails, clear local session
                    self.clearSession();
                    $location.path('/login');
                    return {
                        success: true,
                        message: 'Logged out'
                    };
                });
        };

        /**
         * Change user's PIN
         */
        self.changePin = function(currentPin, newPin, confirmPin) {
            return $http.post('/auth/change-pin', {
                current_pin: currentPin,
                new_pin: newPin,
                confirm_pin: confirmPin
            })
            .then(function(response) {
                return {
                    success: response.data.success || false,
                    message: response.data.message || 'PIN change completed'
                };
            })
            .catch(function(error) {
                var message = 'PIN change failed';
                if (error.data && error.data.message) {
                    message = error.data.message;
                }

                return {
                    success: false,
                    message: message
                };
            });
        };

        /**
         * Clear session data
         */
        self.clearSession = function() {
            self.currentUser = null;
            self.isAuthenticated = false;
            self.isAdmin = false;
            self.stopSessionMonitoring();
        };

        /**
         * Start monitoring session validity
         */
        self.startSessionMonitoring = function() {
            // Stop any existing interval
            self.stopSessionMonitoring();

            // Check session every 5 minutes
            sessionCheckInterval = $interval(function() {
                self.checkAuthenticationStatus().then(function(isAuth) {
                    if (!isAuth && $location.path() !== '/login') {
                        // Session expired, redirect to login
                        console.log('Session expired, redirecting to login');
                        $location.path('/login');
                    }
                });
            }, 5 * 60 * 1000); // 5 minutes
        };

        /**
         * Stop session monitoring
         */
        self.stopSessionMonitoring = function() {
            if (sessionCheckInterval) {
                $interval.cancel(sessionCheckInterval);
                sessionCheckInterval = null;
            }
        };

        /**
         * Check if user has admin privileges
         */
        self.requireAdmin = function() {
            return self.isAuthenticated && self.isAdmin;
        };

        /**
         * Get current user information
         */
        self.getCurrentUser = function() {
            return self.currentUser;
        };

        /**
         * Initialize authentication service
         */
        self.initialize = function() {
            return self.checkAuthenticationStatus();
        };

        // Cleanup on service destroy
        self.$onDestroy = function() {
            self.stopSessionMonitoring();
        };
    });

})();
