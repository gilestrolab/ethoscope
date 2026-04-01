(function() {
    'use strict';

    var app = angular.module('flyApp');

    // Custom tooltip directive for ethoscope interface
    app.directive('tooltip', function($compile) {
        return {
            restrict: 'A',
            link: function(scope, element, attrs) {
                // Create tooltip element
                var tooltipElement = angular.element('<div class="custom-tooltip">{{tooltipText}}</div>');
                tooltipElement.addClass('tooltip-hidden');
                element.after(tooltipElement);

                // Set tooltip text from the `tooltip` attribute
                var tooltipText = attrs.tooltip || '';
                scope.tooltipText = tooltipText;

                // Compile the tooltip element to enable Angular binding
                $compile(tooltipElement)(scope);

                // Tooltip visibility logic
                var showTooltip = function() {
                    tooltipElement.removeClass('tooltip-hidden');
                    tooltipElement.addClass('tooltip-visible');
                };

                var hideTooltip = function() {
                    tooltipElement.removeClass('tooltip-visible');
                    tooltipElement.addClass('tooltip-hidden');
                };

                // Attach mouseover and mouseleave events for tooltip visibility
                element.on('mouseenter', function() {
                    scope.$apply(showTooltip);
                });

                element.on('mouseleave', function() {
                    scope.$apply(hideTooltip);
                });

                // Clean up event listeners on destroy
                scope.$on('$destroy', function() {
                    element.off('mouseenter');
                    element.off('mouseleave');
                });
            }
        };
    });

    // URL sanitization configuration
    app.config(['$compileProvider', function($compileProvider) {
        $compileProvider.aHrefSanitizationWhitelist(/^\s*(https?|ftp|mailto|file|sms|tel|ssh):/);
    }]);

})();
