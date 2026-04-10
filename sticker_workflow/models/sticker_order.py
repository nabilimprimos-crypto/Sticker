from odoo import api, fields, models, _
from odoo.exceptions import UserError


class StickerOrder(models.Model):
    _name = 'sticker.order'
    _description = 'Commande de fabrication sticker'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'priority desc, date_order desc, id desc'

    # ── Identification ───────────────────────────────────────────────
    name = fields.Char(
        string='Référence',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('Nouveau'),
    )
    partner_id = fields.Many2one(
        'res.partner', string='Client', required=True, tracking=True)
    sale_order_id = fields.Many2one(
        'sale.order', string='Bon de commande', tracking=True)

    date_order = fields.Datetime(
        string='Date commande', default=fields.Datetime.now, tracking=True)
    date_deadline = fields.Date(
        string='Date de livraison souhaitée', tracking=True)

    # ── Détails du sticker ───────────────────────────────────────────
    product_name = fields.Char(string='Désignation sticker', required=True)
    quantity = fields.Integer(string='Quantité', default=1, required=True)
    width_mm = fields.Float(string='Largeur (mm)')
    height_mm = fields.Float(string='Hauteur (mm)')
    material = fields.Selection([
        ('vinyl', 'Vinyle'),
        ('paper', 'Papier'),
        ('polyester', 'Polyester'),
        ('transparent', 'Transparent'),
    ], string='Matière', default='vinyl')
    finish = fields.Selection([
        ('glossy', 'Brillant'),
        ('matte', 'Mat'),
        ('uv', 'Vernis UV'),
    ], string='Finition', default='glossy')
    cut_type = fields.Selection([
        ('square', 'Carré / Rectangle'),
        ('contour', 'Découpe à la forme'),
        ('kiss_cut', 'Kiss-cut'),
    ], string='Type de découpe', default='square')

    # ── Artwork / fichier ────────────────────────────────────────────
    artwork_state = fields.Selection([
        ('pending',  'En attente'),
        ('received', 'Reçu'),
        ('approved', 'Validé'),
        ('rejected', 'Rejeté'),
    ], string='État artwork', default='pending', tracking=True)
    artwork_notes = fields.Text(string='Notes artwork')

    # ── Workflow / Kanban ────────────────────────────────────────────
    stage_id = fields.Many2one(
        'sticker.stage',
        string='Étape',
        group_expand='_read_group_stage_ids',
        default=lambda self: self._default_stage(),
        tracking=True,
        index=True,
    )
    kanban_state = fields.Selection([
        ('normal',   'En cours'),
        ('done',     'Prêt pour la suite'),
        ('blocked',  'Bloqué'),
    ], string='État Kanban', default='normal', tracking=True)
    priority = fields.Selection([
        ('0', 'Normal'),
        ('1', 'Urgent'),
    ], string='Priorité', default='0')
    color = fields.Integer(string='Couleur Kanban')

    # ── Responsables ─────────────────────────────────────────────────
    user_id = fields.Many2one(
        'res.users', string='Responsable',
        default=lambda self: self.env.user, tracking=True)
    printer_id = fields.Many2one(
        'res.users', string='Opérateur impression', tracking=True)
    cutter_id = fields.Many2one(
        'res.users', string='Opérateur découpe', tracking=True)

    # ── Dates de passage par étape ────────────────────────────────────
    date_printing_start = fields.Datetime(string='Début impression')
    date_printing_end = fields.Datetime(string='Fin impression')
    date_cutting_end = fields.Datetime(string='Fin découpe/finition')
    date_qc = fields.Datetime(string='Date contrôle qualité')
    date_shipped = fields.Datetime(string='Date expédition')

    # ── Notes ────────────────────────────────────────────────────────
    notes = fields.Html(string='Notes internes')

    # ────────────────────────────────────────────────────────────────
    def _default_stage(self):
        return self.env['sticker.stage'].search([], order='sequence', limit=1)

    @api.model
    def _read_group_stage_ids(self, stages, domain, order):
        return stages.search([], order=order)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('Nouveau')) == _('Nouveau'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'sticker.order') or _('Nouveau')
        return super().create(vals_list)

    # ── Boutons d'action rapide ───────────────────────────────────────
    def action_next_stage(self):
        for rec in self:
            next_stage = self.env['sticker.stage'].search(
                [('sequence', '>', rec.stage_id.sequence)],
                order='sequence', limit=1)
            if next_stage:
                rec.stage_id = next_stage
            else:
                raise UserError(_('Cette commande est déjà à la dernière étape.'))

    def action_mark_artwork_approved(self):
        self.artwork_state = 'approved'

    def action_mark_artwork_rejected(self):
        self.artwork_state = 'rejected'

    def action_start_printing(self):
        self.date_printing_start = fields.Datetime.now()
        self.kanban_state = 'normal'

    def action_end_printing(self):
        self.date_printing_end = fields.Datetime.now()
        self.kanban_state = 'done'

    def action_ship(self):
        self.date_shipped = fields.Datetime.now()
        done_stage = self.env['sticker.stage'].search(
            [('is_done', '=', True)], limit=1)
        if done_stage:
            self.stage_id = done_stage
