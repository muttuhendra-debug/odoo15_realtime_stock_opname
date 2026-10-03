odoo.define('realtime_stock_opname.stock_reconciliation_list_button', function (require) {
"use strict";

var ListController = require('web.ListController');
var ListView = require('web.ListView');
var viewRegistry = require('web.view_registry');

var StockReconciliationListController = ListController.extend({
    init: function () {
        this._super.apply(this, arguments);
        this.hasButtons = true;
    },

    renderButtons: function ($node) {
        this._super.apply(this, arguments);
        if (!this.$buttons) {
            this.$buttons = $('<div>', { class: 'o_list_buttons', role: 'toolbar' });
            if ($node) {
                this.$buttons.appendTo($node);
            }
        }
        if (this.$buttons && !this.$buttons.find('.o_button_tarik_data').length) {
            var $btn = $('<button>', {
                type: 'button',
                class: 'btn btn-primary o_button_tarik_data',
                text: 'Tarik Data',
                style: 'margin-bottom: 4px;'
            });
            this.$buttons.append($btn);

            var self = this;
            this.$buttons.on('click', '.o_button_tarik_data', function () {
                self.do_action({
                    name: 'Stock Reconciliation',
                    type: 'ir.actions.act_window',
                    res_model: 'stock.reconciliation.wizard',
                    view_mode: 'form',
                    views: [[false, 'form']],
                    target: 'new',
                });
            });
        }
    },
});

var StockReconciliationListView = ListView.extend({
    config: _.extend({}, ListView.prototype.config, {
        Controller: StockReconciliationListController,
    }),
});

viewRegistry.add('stock_reconciliation_list_button', StockReconciliationListView);

return {
    StockReconciliationListController: StockReconciliationListController,
    StockReconciliationListView: StockReconciliationListView,
};

});
