from odoo import fields, models


class StickerStage(models.Model):
    _name = 'sticker.stage'
    _description = 'Étape de fabrication'
    _order = 'sequence, id'

    name = fields.Char(string='Étape', required=True, translate=True)
    sequence = fields.Integer(default=10)
    description = fields.Text(translate=True)
    fold = fields.Boolean(string='Plié dans le Kanban', default=False)
    is_done = fields.Boolean(string='Étape finale', default=False)
    color = fields.Integer(string='Couleur')

    # Boutons d'action rapide dans le Kanban
    legend_blocked = fields.Char(
        string='Légende bloqué', default='Bloqué', translate=True)
    legend_done = fields.Char(
        string='Légende prêt', default='Prêt pour l\'étape suivante', translate=True)
    legend_normal = fields.Char(
        string='Légende en cours', default='En cours', translate=True)
