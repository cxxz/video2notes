#!/usr/bin/env python3
"""
Main entry point for the Video2Notes application.
"""
import os
import logging
from app import create_app

def main():
    """Main entry point."""
    # Determine environment
    config_name = os.getenv('FLASK_ENV', 'development')
    
    # Create Flask application
    app = create_app(config_name)
    
    # Get configuration
    port = app.config.get('MAIN_APP_PORT', 5100)
    debug = app.config.get('DEBUG', False)
    
    # Set up logging for production
    if not debug:
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s %(levelname)s: %(message)s'
        )
    
    # Log startup information
    app.logger.info("🚀 Starting Video2Notes Web Application")
    app.logger.info(f"📝 Access the application at: http://0.0.0.0:{port}")
    app.logger.info("🔧 Using modular Flask blueprints architecture")
    
    # Create static directory if it doesn't exist
    os.makedirs('app/static/css', exist_ok=True)
    os.makedirs('app/static/js', exist_ok=True)
    
    # Run the application
    app.run(
        host='0.0.0.0', 
        port=port, 
        debug=debug, 
        threaded=True
    )

if __name__ == '__main__':
    main()
