odoo.define('realtime_stock_opname.barcode_autofocus', function (require) {
"use strict";

var FormRenderer = require('web.FormRenderer');

FormRenderer.include({
    _render: function () {
        var self = this;
        return this._super.apply(this, arguments).then(function () {
            if (self.state && self.state.model === 'realtime.stock.opname') {
                self._attachBarcodeAutofocus();
            }
        });
    },

    confirmUpdate: function (state, id, fields) {
        var self = this;
        return this._super.apply(this, arguments).then(function (result) {
            if (state && state.model === 'realtime.stock.opname') {
                if (fields && fields.includes('barcode_scan')) {
                    setTimeout(function () {
                        self._focusLastQuantityInput();
                    }, 200);
                }
            }
            return result;
        });
    },

    _attachBarcodeAutofocus: function () {
        var self = this;
        this.$el.off('keydown.barcode_autofocus', 'input[name="barcode_scan"]')
            .on('keydown.barcode_autofocus', 'input[name="barcode_scan"]', function (e) {
                if (e.which === 13) { // Enter key pressed
                    setTimeout(function () {
                        self._focusLastQuantityInput();
                    }, 300);
                }
            });
    },

    _focusLastQuantityInput: function () {
        var $qtyInputs = this.$('div[name="line_ids"] tr td[name="quantity"] input, div[name="line_ids"] tr input.o_field_number');
        if ($qtyInputs.length > 0) {
            var $lastInput = $qtyInputs.last();
            $lastInput.focus();
            if ($lastInput[0] && typeof $lastInput[0].select === 'function') {
                $lastInput[0].select();
            }
        }
    }
});

});
