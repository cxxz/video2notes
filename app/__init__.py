"""
Flask application factory for Video2Notes.
"""
import logging
import os
from typing import Optional

from flask import Flask
from dotenv import load_dotenv

from .config import config


def create_app(config_name: Optional[str] = None) -> Flask:
    """Create and configure Flask application."""
    
    # Load environment variables
    load_dotenv()
    
    # Determine configuration
    if config_name is None:
        config_name = os.getenv('FLASK_ENV', 'default')
    
    # Create Flask application
    app = Flask(__name__)
    app.config.from_object(config[config_name])
    
    # Initialize configuration
    config[config_name].init_directories()
    
    # Set up logging
    if not app.debug and not app.testing:
        logging.basicConfig(level=logging.INFO)
        app.logger.setLevel(logging.INFO)
    
    # Register blueprints (will be created later)
    register_blueprints(app)
    
    # Log startup information
    app.logger.info("Video2Notes Web Application Starting")
    app.logger.info(f"Configuration: {config_name}")
    app.logger.info(f"Upload folder: {app.config['UPLOAD_FOLDER']}")
    
    return app


def register_blueprints(app: Flask) -> None:
    """Register all application blueprints."""
    
    # Import blueprints here to avoid circular imports
    # These will be created in later phases
    try:
        from .routes.main import main_bp
        from .routes.workflow import workflow_bp
        from .routes.files import files_bp
        from .routes.slides import slides_bp
        from .routes.speakers import speakers_bp
        
        app.register_blueprint(main_bp)
        app.register_blueprint(workflow_bp, url_prefix='/workflow')
        app.register_blueprint(files_bp, url_prefix='/files')
        app.register_blueprint(slides_bp, url_prefix='/slides')
        app.register_blueprint(speakers_bp, url_prefix='/speakers')
        
    except ImportError:
        # Blueprints not created yet, register a temporary main route
        @app.route('/')
        def index():
            return "Video2Notes - Refactoring in progress..."
        
        app.logger.warning("Using temporary routes - blueprints not yet created")