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
        var self = this;
        if (this.$buttons) {
            if (!this.$buttons.find('.o_button_tarik_data').length) {
                var $btn = $('<button>', {
                    type: 'button',
                    class: 'btn btn-primary o_button_tarik_data',
                    text: 'Tarik Data',
                    style: 'margin-bottom: 4px;'
                });
                this.$buttons.append($btn);
            }
            this.$buttons.off('click', '.o_button_tarik_data').on('click', '.o_button_tarik_data', function (ev) {
                if (ev) {
                    ev.preventDefault();
                    ev.stopPropagation();
                }
                self.do_action('realtime_stock_opname.action_stock_reconciliation_wizard');
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
