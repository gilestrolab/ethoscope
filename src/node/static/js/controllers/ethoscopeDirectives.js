(function() {
    'use strict';

    var app = angular.module('flyApp');

    // Custom tooltip directive for ethoscope interface
    app.directive('tooltip', function($compile) {
        return {
            restrict: 'A',
            link: function(scope, element, attrs) {
                // Create tooltip element
                const tooltipElement = angular.element('<div class="custom-tooltip">{{tooltipText}}</div>');
                tooltipElement.addClass('tooltip-hidden');
                element.after(tooltipElement);

                // Set tooltip text from the `tooltip` attribute
                let tooltipText = attrs.tooltip || '';
                scope.tooltipText = tooltipText;

                // Compile the tooltip element to enable Angular binding
                $compile(tooltipElement)(scope);

                // Tooltip visibility logic
                const showTooltip = () => {
                    tooltipElement.removeClass('tooltip-hidden');
                    tooltipElement.addClass('tooltip-visible');
                };

                const hideTooltip = () => {
                    tooltipElement.removeClass('tooltip-visible');
                    tooltipElement.addClass('tooltip-hidden');
                };

                // Attach mouseover and mouseleave events for tooltip visibility
                element.on('mouseenter', () => {
                    scope.$apply(showTooltip);
                });

                element.on('mouseleave', () => {
                    scope.$apply(hideTooltip);
                });

                // Clean up event listeners on destroy
                scope.$on('$destroy', () => {
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
