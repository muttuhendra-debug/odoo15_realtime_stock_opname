odoo.define('realtime_stock_opname.camera_scanner', function (require) {
"use strict";

var AbstractAction = require('web.AbstractAction');
var core = require('web.core');
var Dialog = require('web.Dialog');
var _t = core._t;

var CameraScannerAction = AbstractAction.extend({
    template: 'realtime_stock_opname.CameraScannerTemplate',
    events: {
        'click .o_btn_close_scanner': '_onCloseScanner',
        'click .o_btn_submit_manual_barcode': '_onSubmitManualBarcode',
        'change .o_input_camera_file': '_onCameraFileChange',
        'click .o_btn_toggle_flash': '_onToggleFlash',
    },

    init: function (parent, action) {
        this._super.apply(this, arguments);
        this.action = action;
        this.context = action.context || {};
        this.active_id = this.context.active_id || this.context.default_opname_id;
        this.mediaStream = null;
        this.scanInterval = null;
        this.lastDetectedCode = null;
        this.detectionCount = 0;
        this.isFlashOn = false;
    },

    _getInlineTemplate: function () {
        return '<div class="o_camera_scanner_container text-center p-3">' +
            '<div class="card shadow-sm mx-auto" style="max-width: 500px;">' +
                '<div class="card-header bg-primary text-white d-flex justify-content-between align-items-center">' +
                    '<h5 class="m-0"><i class="fa fa-camera mr-2"></i>Smartphone Barcode Scanner</h5>' +
                    '<div>' +
                        '<button type="button" class="btn btn-warning btn-sm mr-2 o_btn_toggle_flash" title="Toggle Flashlight">' +
                            '<i class="fa fa-bolt mr-1"></i> Flash' +
                        '</button>' +
                        '<button type="button" class="close text-white o_btn_close_scanner" aria-label="Close">' +
                            '<span aria-hidden="true">&#215;</span>' +
                        '</button>' +
                    '</div>' +
                '</div>' +
                '<div class="card-body">' +
                    '<div class="mb-3">' +
                        '<label class="btn btn-success btn-block btn-lg m-0 shadow-sm cursor-pointer" style="font-size: 1.1rem; cursor: pointer;">' +
                            '<i class="fa fa-camera mr-2"></i>Take Photo / Scan Barcode' +
                            '<input type="file" class="o_input_camera_file d-none" accept="image/*" capture="environment"/>' +
                        '</label>' +
                    '</div>' +
                    '<div class="o_camera_video_wrapper position-relative mb-3 bg-dark rounded overflow-hidden" style="max-height: 260px; min-height: 180px;">' +
                        '<style>' +
                            '.o_camera_video_wrapper video, .o_camera_video_wrapper canvas, .o_camera_video_wrapper img { width: 100% !important; max-height: 260px !important; object-fit: cover !important; }' +
                            '.o_camera_video_wrapper canvas.drawingBuffer { position: absolute !important; top: 0 !important; left: 0 !important; width: 100% !important; height: 100% !important; }' +
                        '</style>' +
                        '<video class="o_camera_video w-100" style="max-height: 260px; object-fit: cover;" playsinline="true"></video>' +
                        '<img class="o_camera_preview_img d-none w-100" style="max-height: 260px; object-fit: cover;" alt="Captured Barcode Photo"/>' +
                    '</div>' +
                    '<div class="alert alert-info o_camera_status mb-3">' +
                        _t("Align barcode within camera view or tap 'Take Photo' above...") +
                    '</div>' +
                    '<div class="input-group">' +
                        '<input type="text" class="form-control o_input_manual_barcode" placeholder="' + _t("Enter barcode manually if needed...") + '"/>' +
                        '<div class="input-group-append">' +
                            '<button class="btn btn-primary o_btn_submit_manual_barcode" type="button">' + _t("Process") + '</button>' +
                        '</div>' +
                    '</div>' +
                '</div>' +
                '<div class="card-footer text-right">' +
                    '<button class="btn btn-secondary o_btn_close_scanner" type="button">' + _t("Done / Close") + '</button>' +
                '</div>' +
            '</div>' +
        '</div>';
    },

    renderElement: function () {
        if (core.qweb && core.qweb.has_template(this.template)) {
            this._super.apply(this, arguments);
        } else {
            var $el = $(this._getInlineTemplate());
            this._replaceElement($el);
        }
    },

    start: function () {
        var self = this;
        return this._super.apply(this, arguments).then(function () {
            self._startCamera();
        });
    },

    _startCamera: function () {
        var self = this;
        var wrapperElement = this.$('.o_camera_video_wrapper')[0];

        if (window.Quagga && wrapperElement) {
            try {
                window.Quagga.init({
                    inputStream: {
                        name: "Live",
                        type: "LiveStream",
                        target: wrapperElement,
                        constraints: {
                            facingMode: "environment",
                            width: { min: 1280, ideal: 1920 },
                            height: { min: 720, ideal: 1080 },
                            aspectRatio: { min: 1, max: 2 }
                        },
                        area: {
                            top: "10%",
                            right: "10%",
                            left: "10%",
                            bottom: "10%"
                        }
                    },
                    locator: {
                        halfSample: false,
                        patchSize: "large"
                    },
                    numOfWorkers: 0,
                    frequency: 10,
                    decoder: {
                        readers: [
                            "code_128_reader",
                            "code_39_reader",
                            "ean_reader",
                            "ean_8_reader",
                            "upc_reader",
                            "upc_e_reader"
                        ],
                        multiple: false
                    },
                    locate: true
                }, function (err) {
                    if (err) {
                        console.warn("Quagga live stream init error:", err);
                        self.$('.o_camera_status').html(
                            _t("Tap <b>'Take Photo / Scan Barcode'</b> above to scan using your smartphone camera!")
                        );
                        return;
                    }
                    window.Quagga.start();

                    // Apply continuous autofocus & HD stream optimization
                    try {
                        var track = window.Quagga.CameraAccess.getActiveTrack();
                        if (track && typeof track.applyConstraints === 'function') {
                            track.applyConstraints({
                                advanced: [
                                    { focusMode: 'continuous' },
                                    { focusDistance: 0 },
                                    { pointsOfInterest: [{ x: 0.5, y: 0.5 }] }
                                ]
                            }).catch(function (e) {
                                console.log("Camera autofocus constraint note:", e);
                            });
                        }
                    } catch (e) {}

                    // Native BarcodeDetector fallback/boost for high accuracy on Chrome/Android
                    self._startNativeBarcodeDetector(wrapperElement);

                    // Provide visual feedback boxes on stream
                    window.Quagga.onProcessed(function (result) {
                        var drawingCtx = window.Quagga.canvas.ctx.overlay;
                        var drawingCanvas = window.Quagga.canvas.dom.overlay;

                        if (result && drawingCtx && drawingCanvas) {
                            drawingCtx.clearRect(0, 0, parseInt(drawingCanvas.getAttribute("width")), parseInt(drawingCanvas.getAttribute("height")));
                            if (result.boxes) {
                                result.boxes.filter(function (box) {
                                    return box !== result.box;
                                }).forEach(function (box) {
                                    window.Quagga.ImageDebug.drawPath(box, { x: 0, y: 1 }, drawingCtx, { color: "green", lineWidth: 2 });
                                });
                            }
                            if (result.box) {
                                window.Quagga.ImageDebug.drawPath(result.box, { x: 0, y: 1 }, drawingCtx, { color: "#00F", lineWidth: 2 });
                            }
                            if (result.codeResult && result.codeResult.code) {
                                window.Quagga.ImageDebug.drawPath(result.line, { x: 'x', y: 'y' }, drawingCtx, { color: 'red', lineWidth: 3 });
                            }
                        }
                    });

                    window.Quagga.onDetected(function (result) {
                        if (!result || !result.codeResult || !result.codeResult.code) {
                            return;
                        }

                        // Calculate average decoding error to prevent false positives for Code 128
                        var code = result.codeResult.code;
                        var errors = result.codeResult.decodedCodes
                            .filter(function (c) { return c.error !== undefined; })
                            .map(function (c) { return c.error; });

                        var avgError = errors.length ? errors.reduce(function (a, b) { return a + b; }, 0) / errors.length : 0;

                        // Filter out low-confidence readings (avg error threshold 0.15)
                        if (avgError > 0.15) {
                            return;
                        }

                        // Require 2 consecutive matching reads or high accuracy match
                        if (self.lastDetectedCode === code) {
                            self.detectionCount += 1;
                        } else {
                            self.lastDetectedCode = code;
                            self.detectionCount = 1;
                        }

                        if (self.detectionCount >= 2) {
                            window.Quagga.stop();
                            self._handleDetectedBarcode(code);
                        }
                    });
                });
                return;
            } catch (e) {
                console.warn("Quagga init failed:", e);
            }
        }

        self.$('.o_camera_status').html(
            _t("Tap <b>'Take Photo / Scan Barcode'</b> above to scan using your smartphone camera!")
        );
    },

    _onToggleFlash: function (e) {
        e.preventDefault();
        var self = this;
        this.isFlashOn = !this.isFlashOn;
        var torchState = this.isFlashOn;

        try {
            var track = null;
            if (window.Quagga && window.Quagga.CameraAccess) {
                track = window.Quagga.CameraAccess.getActiveTrack();
            }
            if (!track && this.mediaStream) {
                var tracks = this.mediaStream.getVideoTracks();
                if (tracks.length > 0) {
                    track = tracks[0];
                }
            }

            if (track && typeof track.applyConstraints === 'function') {
                track.applyConstraints({
                    advanced: [{ torch: torchState }]
                }).then(function () {
                    self.$('.o_btn_toggle_flash').toggleClass('btn-warning btn-light');
                    self.displayNotification({
                        title: _t("Flashlight"),
                        message: torchState ? _t("Flashlight turned ON") : _t("Flashlight turned OFF"),
                        type: 'info',
                    });
                }).catch(function (err) {
                    console.warn("Torch constraint not supported on this device/browser:", err);
                    Dialog.alert(self, _t("Flashlight is not supported or permitted on this device/browser."));
                    self.isFlashOn = !torchState;
                });
            } else {
                Dialog.alert(self, _t("Flashlight control is not available on this camera track."));
            }
        } catch (err) {
            console.warn("Error toggling flash:", err);
            Dialog.alert(self, _t("Flashlight control error on this device."));
        }
    },

    _startNativeBarcodeDetector: function (wrapperElement) {
        var self = this;
        if (!('BarcodeDetector' in window)) {
            return;
        }

        try {
            var nativeDetector = new BarcodeDetector({
                formats: ['code_128', 'code_39', 'ean_13', 'ean_8', 'upc_a', 'upc_e']
            });

            this.scanInterval = setInterval(function () {
                var videoElem = wrapperElement.querySelector('video');
                if (videoElem && videoElem.readyState >= 2 && !self.isProcessing) {
                    nativeDetector.detect(videoElem).then(function (barcodes) {
                        if (barcodes && barcodes.length > 0 && barcodes[0].rawValue) {
                            var detected = barcodes[0].rawValue.trim();
                            if (detected) {
                                self._stopCamera();
                                self._handleDetectedBarcode(detected);
                            }
                        }
                    }).catch(function () {});
                }
            }, 300);
        } catch (e) {
            console.log("Native BarcodeDetector stream check exception:", e);
        }
    },

    _onCameraFileChange: function (e) {
        var self = this;
        var files = e.target.files;
        if (!files || files.length === 0) {
            return;
        }
        var file = files[0];
        var reader = new FileReader();
        self.$('.o_camera_status').text(_t("Processing photo..."));

        reader.onload = function (event) {
            var dataUrl = event.target.result;

            // Show captured photo preview in the video wrapper box
            self.$('.o_camera_video').addClass('d-none');
            self.$('.o_camera_preview_img').attr('src', dataUrl).removeClass('d-none');

            // 1. First try native BarcodeDetector API for highest Code 128 precision on photos
            self._tryBarcodeDetectorOnImage(dataUrl, function (success) {
                if (success) {
                    return;
                }
                // 2. Fallback to Quagga JS decodeSingle with large patch size
                if (window.Quagga) {
                    window.Quagga.decodeSingle({
                        src: dataUrl,
                        numOfWorkers: 0,
                        locator: {
                            halfSample: false,
                            patchSize: "large"
                        },
                        decoder: {
                            readers: ["code_128_reader", "code_39_reader", "ean_reader", "ean_8_reader", "upc_reader"]
                        },
                        locate: true
                    }, function (result) {
                        if (result && result.codeResult && result.codeResult.code) {
                            self._handleDetectedBarcode(result.codeResult.code);
                        } else {
                            self.$('.o_camera_status').text(_t("Photo loaded. No barcode detected automatically. Please type barcode below."));
                        }
                    });
                }
            });
        };
        reader.readAsDataURL(file);
    },

    _tryBarcodeDetectorOnImage: function (dataUrl, callback) {
        var self = this;
        var img = new Image();
        img.onload = function () {
            if ('BarcodeDetector' in window) {
                try {
                    var detector = new BarcodeDetector({ formats: ['code_128', 'code_39', 'ean_13', 'upc_a'] });
                    detector.detect(img).then(function (barcodes) {
                        if (barcodes && barcodes.length > 0 && barcodes[0].rawValue) {
                            self._handleDetectedBarcode(barcodes[0].rawValue);
                            if (callback) callback(true);
                        } else {
                            if (callback) callback(false);
                        }
                    }).catch(function (err) {
                        if (callback) callback(false);
                    });
                    return;
                } catch (e) {}
            }
            if (callback) callback(false);
        };
        img.src = dataUrl;
    },

    _handleDetectedBarcode: function (barcode) {
        var cleanCode = String(barcode).trim();
        if (!cleanCode) {
            return;
        }

        this.$('.o_input_manual_barcode').val(cleanCode);
        this.$('.o_camera_status').html(_t("<b>Detected Barcode:</b> ") + cleanCode);

        this._onBarcodeScanned(cleanCode);
    },

    _onBarcodeScanned: function (barcode) {
        var self = this;
        if (this.isProcessing) {
            return;
        }
        this.isProcessing = true;
        this._stopCamera();

        this._rpc({
            model: 'realtime.stock.opname',
            method: 'process_scanned_barcode',
            args: [this.active_id, barcode],
        }).then(function (res) {
            self._stopCamera();
            if (res && typeof res === 'object' && res.type === 'ir.actions.act_window') {
                self.do_action(res);
            } else {
                self.displayNotification({
                    title: _t("Barcode Scanned"),
                    message: _t("Product processed successfully: ") + barcode,
                    type: 'success',
                });
                self._closeAndReload();
            }
        }).catch(function (error) {
            self.isProcessing = false;
            Dialog.alert(self, error.data ? error.data.message : _t("Error processing barcode: ") + barcode);
        });
    },

    _onSubmitManualBarcode: function (e) {
        e.preventDefault();
        var manualCode = this.$('.o_input_manual_barcode').val();
        if (manualCode && manualCode.trim()) {
            this._onBarcodeScanned(manualCode.trim());
        }
    },

    _stopCamera: function () {
        if (window.Quagga) {
            try { window.Quagga.stop(); } catch (e) {}
        }
        if (this.scanInterval) {
            clearInterval(this.scanInterval);
            this.scanInterval = null;
        }
        if (this.mediaStream) {
            this.mediaStream.getTracks().forEach(function (track) {
                track.stop();
            });
            this.mediaStream = null;
        }
    },

    _onCloseScanner: function () {
        this._stopCamera();
        this._closeAndReload();
    },

    _closeAndReload: function () {
        this._stopCamera();
        this.do_action({'type': 'ir.actions.act_window_close'});
    },

    destroy: function () {
        this._stopCamera();
        this._super.apply(this, arguments);
    }
});

core.action_registry.add('realtime_stock_opname_camera_scan', CameraScannerAction);

return CameraScannerAction;

});
