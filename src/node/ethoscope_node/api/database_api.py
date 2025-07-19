"""
Database API Module

Handles database queries for runs and experiments.
"""

import json
from .base import BaseAPI, error_decorator


class DatabaseAPI(BaseAPI):
    """API endpoints for database queries."""
    
    def register_routes(self):
        """Register database-related routes."""
        self.app.route('/runs_list', method='GET')(self._runs_list)
        self.app.route('/experiments_list', method='GET')(self._experiments_list)
    
    @error_decorator
    def _runs_list(self):
        """Get all runs from database."""
        return json.dumps(self.database.getRun('all', asdict=True))
    
    @error_decorator
    def _experiments_list(self):
        """Get all experiments from database."""
        return json.dumps(self.database.getExperiment('all', asdict=True))