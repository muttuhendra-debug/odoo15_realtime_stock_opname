odoo.define('realtime_stock_opname.stock_reconciliation_list_button', function (require) {
"use strict";

var ListController = require('web.ListController');
var ListView = require('web.ListView');
var viewRegistry = require('web.view_registry');

var StockReconciliationListController = ListController.extend({
    renderButtons: function ($node) {
        this._super.apply(this, arguments);
        if (this.$buttons) {
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
