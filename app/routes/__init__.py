from app.routes.dashboard import dashboard_bp
from app.routes.products import products_bp
from app.routes.research import research_bp
from app.routes.settings import settings_bp


def register_blueprints(app):
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(research_bp)
    app.register_blueprint(settings_bp)
