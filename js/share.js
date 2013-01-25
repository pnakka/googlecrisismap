// Copyright 2012 Google Inc.  All Rights Reserved.
//
// Licensed under the Apache License, Version 2.0 (the "License"); you may not
// use this file except in compliance with the License.  You may obtain a copy
// of the License at: http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software distrib-
// uted under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
// OR CONDITIONS OF ANY KIND, either express or implied.  See the License for
// specific language governing permissions and limitations under the License.

/**
 * @fileoverview Creates the popup and button for the share functionality.
 * @author arb@google.com (Anthony Baxter)
 */
goog.provide('cm.ShareBox');
goog.provide('cm.ShareButton');
goog.provide('cm.SharePopup');

goog.require('cm.AppState');
goog.require('cm.events');
goog.require('cm.ui');
goog.require('goog.Disposable');
goog.require('goog.Uri');
goog.require('goog.dom.classes');
goog.require('goog.json');
goog.require('goog.net.Jsonp');
goog.require('goog.ui.BidiInput');
goog.require('goog.ui.Popup');


/**
 * A button that when clicked displays the associated SharePopup.
 * @param {!google.maps.Map} map The map on which to place the Share button.
 * @param {!cm.AppState} appState The application state model.
 * @param {boolean} showFacebookButton Show the Facebook button in the popup?
 * @param {boolean} showGooglePlusButton Show the Google+ button in the popup?
 * @param {boolean} showTwitterButton Show the Twitter button in the popup?
 * @constructor
 * @extends {goog.Disposable}
 */
cm.ShareButton = function(map, appState, showFacebookButton,
                          showGooglePlusButton, showTwitterButton) {
  goog.Disposable.call(this);

  var button = cm.ui.create('div', {'class': 'cm-mapbutton', 'index': 1},
      cm.ShareButton.MSG_SHARE_BUTTON_);
  map.controls[google.maps.ControlPosition.TOP_RIGHT].push(button);

  /**
   * @type {!cm.SharePopup}
   * @private
   */
  this.popup_ = new cm.SharePopup(appState, button, showFacebookButton,
                                  showGooglePlusButton, showTwitterButton);

  // When the button is clicked, show the popup and make the button selected.
  // 'mousedown' is better than 'click' in this circumstance because it prevents
  // the browser from interpreting a slow click as two click events (which
  // causes the dialog box to "flicker")
  cm.events.listen(button, 'mousedown', function() {
    if (!this.popup_.isVisible()) {
      goog.dom.classes.add(button, 'cm-selected');
      cm.events.emit(goog.global, cm.events.SHARE_BUTTON);
      // TODO(kpy): Let the cm.Presenter open the cm.SharePopup, instead of
      // making the popup private to the cm.ShareButton.  This decoupling will
      // enable us to open the popup from other places, e.g. toolbar or panel.
      this.popup_.show();
    }
  }, this);

  // When the popup goes away, make the button appear unselected.
  cm.events.listen(this.popup_, 'hide', function() {
    goog.dom.classes.remove(button, 'cm-selected');
  }, this);
};
goog.inherits(cm.ShareButton, goog.Disposable);

/** @override */
cm.ShareButton.prototype.disposeInternal = function() {
  cm.events.dispose(this);
  this.popup_.dispose();
};


/**
 * A Closure style popup that displays a share box.
 * @param {!cm.AppState} appState The application state model.
 * @param {Element} button The associated button for this popup.
 * @param {boolean} showFacebookButton Show the Facebook button in the popup?
 * @param {boolean} showGooglePlusButton Show the Google+ button in the popup?
 * @param {boolean} showTwitterButton Show the Twitter button in the popup?
 * @param {goog.dom.DomHelper=} opt_domHelper The (optional) DOM helper.
 * @constructor
 * @extends {goog.Disposable}
 */
cm.SharePopup = function(appState, button, showFacebookButton,
                         showGooglePlusButton, showTwitterButton,
                         opt_domHelper) {
  goog.Disposable.call(this);

  /**
   * @type {Element}
   * @private
   */
  this.button_ = button;

  /**
   * @type {Element}
   * @private
   */
  this.element_ = cm.ui.create('div', {'class': 'cm-share cm-popup'});
  cm.ui.createCloseButton(this.element_, goog.bind(function() {
    this.popup_.setVisible(false);
  }, this));

  /**
   * @type {!cm.ShareBox}
   * @private
   */
  this.shareBox_ = new cm.ShareBox(this.element_, appState, showFacebookButton,
                                   showGooglePlusButton, showTwitterButton,
                                   opt_domHelper);

  /**
   * @type {!goog.ui.Popup}
   * @private
   */
  this.popup_ = new goog.ui.Popup(this.element_);
  this.popup_.setHideOnEscape(true);
  this.popup_.setAutoHide(true);
  this.popup_.setEnableCrossIframeDismissal(false);
  // Forward the 'hide' event to this so that the ShareButton can listen.
  cm.events.forward(this.popup_, 'hide', this);
  // Reposition the popup if the window is resized.
  cm.events.listen(window, 'resize', function() {
    if (this.popup_.isVisible()) {
      cm.ui.showPopup(this.element_);
    }
  }, this);
};
goog.inherits(cm.SharePopup, goog.Disposable);

/** @override */
cm.SharePopup.prototype.disposeInternal = function() {
  this.popup_.dispose();
  this.shareBox_.dispose();
  cm.events.dispose(this);
};

/** Displays the popup. */
cm.SharePopup.prototype.show = function() {
  this.shareBox_.updateLinks();
  this.popup_.setVisible(true);
  cm.ui.showPopup(this.element_);
};

/**
 * Returns whether the popup is visible or not.  Also returns true if the popup
 * was recently visible.  Treating these as the same allows the button to be
 * clicked to close the popup.
 * @return {boolean} True if the popup is visible.
 */
cm.SharePopup.prototype.isVisible = function() {
  return this.popup_.isOrWasRecentlyVisible();
};


/**
 * A share box that offers ways to share links to the current map view.
 * @param {!Element} parentElem The parent element in which to place the box.
 * @param {!cm.AppState} appState The application state model.
 * @param {boolean} showFacebookButton Show the Facebook button in the popup?
 * @param {boolean} showGooglePlusButton Show the Google+ button in the popup?
 * @param {boolean} showTwitterButton Show the Twitter button in the popup?
 * @param {goog.dom.DomHelper=} opt_domHelper The (optional) DOM helper.
 * @constructor
 * @extends {goog.Disposable}
 */
cm.ShareBox = function(parentElem, appState, showFacebookButton,
                       showGooglePlusButton, showTwitterButton, opt_domHelper) {
  goog.Disposable.call(this);

  /**
   * @type {!cm.AppState}
   * @private
   */
  this.appState_ = appState;
  var language = /** @type string */(appState.get('language'));
  var touch = cm.util.browserSupportsTouch();

  /**
   * @type {Element}
   * @private
   */
  this.gplusLink_ = showGooglePlusButton ?
      cm.ShareBox.createGPlusButton_(language) : null;

  /**
   * @type {Element}
   * @private
   */
  this.twitterLink_ = showTwitterButton ?
      cm.ShareBox.createTwitterButton_(language.split('_', 1)[0], touch) : null;

  /**
   * @type {Element}
   * @private
   */
  this.fbFrame_ = showFacebookButton ?
      cm.ShareBox.createFacebookButton_() : null;

  var urlLabelAndInput = cm.ShareBox.createLabelAndInput_(
      'cm-share-url', cm.ShareBox.MSG_SHARE_VIEW_LINK_, opt_domHelper);
  var htmlLabelAndInput = cm.ShareBox.createLabelAndInput_(
      'cm-share-html', cm.ShareBox.MSG_SHARE_VIEW_IFRAME_, opt_domHelper);

  /**
   * @type {Element}
   * @private
   */
  this.shareUrl_ = urlLabelAndInput[1];

  /**
   * @type {Element}
   * @private
   */
  this.shareHtml_ = htmlLabelAndInput[1];

  parentElem.appendChild(cm.ui.create('div', {},
      cm.ui.create('h2', {'class': 'cm-share-header'},
          cm.ShareBox.MSG_SHARE_TITLE_),
      cm.ui.create('ul', {},
          cm.ui.create('div', {'class': 'cm-shorten'},
              // TODO(arb): bidi - reverse label and checkbox order
              this.shortenCheckbox_ = cm.ui.create('input', {
                'type': 'checkbox',
                'class': 'cm-shorten-checkbox',
                'id': 'cm-shorten-checkbox'
              }),
              cm.ui.create('label', {'for': 'cm-shorten-checkbox'},
                  cm.ShareBox.MSG_SHORTEN_URL_LABEL_)
          ),
          cm.ui.create('li', {}, urlLabelAndInput),
          cm.ui.create('li', {}, htmlLabelAndInput),
          cm.ui.create('li', {},
              cm.ui.create('div', {'class': 'cm-social'},
                  this.gplusLink_, this.twitterLink_, this.fbFrame_))
      )
  ));

  cm.events.listen(this.shortenCheckbox_, 'click', function() {
    // The setTimeout call is necessary because IE updates the checked property
    // on the checkbox asynchronously under Puppet.
    goog.global.setTimeout(goog.bind(this.updateLinks, this), 0);
  }, this);
};
goog.inherits(cm.ShareBox, goog.Disposable);

/** @override */
cm.ShareBox.prototype.disposeInternal = function() {
  cm.events.dispose(this);
};

/**
 * Creates an input field with an associated label that automatically selects
 * all the text when the field acquires focus.
 * @param {string} id The DOM element ID for the input field.
 * @param {string} text The text of the label.
 * @param {goog.dom.DomHelper=} opt_domHelper The (optional) DOM helper.
 * @return {Array.<Element>} An array of two elements (label and input).
 * @private
 */
cm.ShareBox.createLabelAndInput_ = function(id, text, opt_domHelper) {
  var inputElem = cm.ui.create('input', {'type': 'text', 'id': id});
  (new goog.ui.BidiInput(opt_domHelper)).decorate(inputElem);
  cm.events.listen(inputElem, 'focus', function() {
    inputElem.select();
    var token = cm.events.listen(inputElem, 'mouseup', function(e) {
      e.preventDefault();  // prevent deselecting on mouseup
      cm.events.unlisten(token);  // restore the original handler
    });
  });
  return [cm.ui.create('label', {'for': id}, text), inputElem];
};

/**
 * Creates the Facebook 'Like' button (in an iframe).
 * @return {!Element} The newly created <iframe>.
 * @private
 */
cm.ShareBox.createFacebookButton_ = function() {
  // It's necessary to create this in an iframe, as the facebook
  // API has no way to dynamically update the URL of a Like button.
  return cm.ui.create('iframe', {
    'class': 'cm-facebook-like-button',
    'scrolling': 'no',
    'allowtransparency': 'true',
    'frameborder': '0',
    // FB iframe handles the browser language correctly, no need to set it.
    'src': new goog.Uri('//www.facebook.com/plugins/like.php').setQueryData(
        goog.Uri.QueryData.createFromMap({
          'layout': 'button_count',
          'width': '90',
          'show_faces': 'false',
          'action': 'like',
          'colorscheme': 'light',
          'font': 'arial',
          'height': '21'
        })
    )
  });
};

/**
 * Creates the Google+ sharing button.
 * @param {string} language The language code to use.
 * @return {!Element} The newly created button, wrapped in a hyperlink.
 * @private
 */
cm.ShareBox.createGPlusButton_ = function(language) {
  // Query parameters on the 'href' attribute are added later by setShareUrl_.
  return cm.ui.create('a', {
    'class': 'cm-gplus-share-button',
    'href': '//plus.google.com/share?hl=' + language,
    'target': '_blank',
    'title': cm.ShareBox.MSG_GPLUS_SHARE_LABEL_
  },
      cm.ui.create('img', {
        'class': 'cm-gplus-img',
        'src': '//ssl.gstatic.com/images/icons/gplus-32.png',
        'alt': cm.ShareBox.MSG_GPLUS_SHARE_LABEL_
      })
  );
};

/**
 * Creates the Twitter sharing button.
 * @param {string} language The 2 char language code to use.
 * @param {boolean} touch Are we on a touch device.
 * @return {!Element} the new DOM node with the sharing button.
 * @private
 */
cm.ShareBox.createTwitterButton_ = function(language, touch) {
  // This whole disaster is needed because the standard twitter.com JS for
  // the twitter button doesn't handle dynamically updated URLs.
  // Twitter uses 2-char language codes. It doesn't support all languages,
  // and it's documentation about which it supports is incomplete. Ah well.
  if (touch) {
    // We skip the iframe on touch-screens because it seemed unreliable on
    // android.
    // TODO(arb): At some point, track down why it's flaky on android.
    return cm.ui.create('a', {
      'class': 'cm-twitter-share-button',
      'href': '//twitter.com/share?lang=' + language,
      'target': '_blank',
      'title': cm.ShareBox.MSG_TWITTER_SHARE_LABEL_
    },
        // TODO(arb): Find proper button? Maybe use the Twitter sprite with
        // offsets, but then we need to address i18n?
        cm.ui.create('div', {
          'class': 'cm-twitter-share-button cm-twitter-img'
        })
    );
  } else {
    // TODO(arb): this leaks internal hostnames with original_referrer when
    // triggered from dev versions (under dev_appserver).
    return cm.ui.create('iframe', {
      'class': 'cm-twitter-share-button',
      'src': '//platform.twitter.com/widgets/tweet_button.html?lang=' +
          language + '&count=none&counturl=http://google.org/crisismap',
      'allowtransparency': 'true',
      'scrolling': 'no'
    });
  }
};

/** Updates the relevant links in the share popup according to the AppState. */
cm.ShareBox.prototype.updateLinks = function() {
  var url = this.appState_.getUri().toString();
  this.setShareUrl_(url);  // update immediately (shortening can take a moment)

  if (this.shortenCheckbox_.checked) {
    var that = this;
    new goog.net.Jsonp(cm.ShareBox.JSON_PROXY_URL).send({
      'url': cm.ShareBox.GOOGL_API_URL,
      'post_json': goog.json.serialize({'longUrl': url})
    }, function(result) { that.setShareUrl_(url, result['id']); });
  }
};

/**
 * Given a URL and an optional shortened URL, sets the links in the share box.
 * @param {goog.Uri|string} url URL to the current map view before shortening.
 * @param {string} opt_shortUrl Shortened URL.
 * @private
 */
cm.ShareBox.prototype.setShareUrl_ = function(url, opt_shortUrl) {
  this.shareUrl_.value = '' + (opt_shortUrl || url);
  // TODO(arb): set the counturl to the map + ID for twitter
  if (this.twitterLink_) {
    if (this.touch_) {
      var twitterHref = new goog.Uri(this.twitterLink_.href);
      twitterHref.setParameterValue('url', opt_shortUrl || url);
      this.twitterLink_.href = twitterHref.toString();
    } else {
      var twitterHref = new goog.Uri(this.twitterLink_.src);
      twitterHref.setParameterValue('url', opt_shortUrl || url);
      this.twitterLink_.src = twitterHref.toString();
    }
  }

  if (this.fbFrame_) {
    var fbUri = new goog.Uri(this.fbFrame_.src);
    fbUri.setParameterValue('href', opt_shortUrl || url);
    this.fbFrame_.src = fbUri.toString();
  }

  if (this.gplusLink_) {
    var gplusUri = new goog.Uri(this.gplusLink_.href);
    // We use the unshortened URL because goo.gl isn't whitelisted for G+.
    gplusUri.setParameterValue('url', url);
    this.gplusLink_.href = gplusUri.toString();
  }

  var iframeUri = new goog.Uri(url);
  iframeUri.setParameterValue('embedded', true);
  this.shareHtml_.value = '<iframe width="400" height="400" src="' +
      iframeUri + '" style="border: 1px solid #ccc"></iframe>';
};

/**
 * @desc Standard label for the 'Share' button on the map.
 * @private
 */
cm.ShareButton.MSG_SHARE_BUTTON_ = goog.getMsg('Share');

/** URL for the goo.gl URL Shortener API. */
cm.ShareBox.GOOGL_API_URL = 'https://www.googleapis.com/urlshortener/v1/url';

/** URL for the JSON proxy. TODO(kpy): make this configurable for CW &c. */
cm.ShareBox.JSON_PROXY_URL = '/crisismap/jsonp';

/**
 * @desc Title for the share box.
 * @private
 */
cm.ShareBox.MSG_SHARE_TITLE_ = goog.getMsg('Share this view');

/**
 * @desc Label for the field containing the link URL to share the map view.
 * @private
 */
cm.ShareBox.MSG_SHARE_URL_LABEL_ = goog.getMsg('Paste link in email or IM');

/**
 * @desc Label for the field containing HTML code to share the map view.
 * @private
 */
cm.ShareBox.MSG_SHARE_HTML_LABEL_ = goog.getMsg(
    'Paste HTML to embed in website');

/**
 * @desc Label for the "Shorten URLs" checkbox in the share popup.
 * @private
 */
cm.ShareBox.MSG_SHORTEN_URL_LABEL_ = goog.getMsg('Shorten URLs');

/**
 * @desc Accessible text for the "Share on G+" button in the share popup.
 * @private
 */
cm.ShareBox.MSG_GPLUS_SHARE_LABEL_ = goog.getMsg('Share on Google+');

/**
 * @desc Accessible text for the "Tweet" button in the share popup.
 * @private
 */
cm.ShareBox.MSG_TWITTER_SHARE_LABEL_ = goog.getMsg('Tweet this map');

// TODO(kpy): After the next round of translations, replace:
// MSG_SHARE_VIEW_LINK_ with MSG_SHARE_URL_LABEL_
// MSG_SHARE_VIEW_IFRAME_ with MSG_SHARE_HTML_LABEL_
// throughout this file, and delete the messages below.

/**
 * @desc Label for the "share this map view as a link" field.
 * @private
 */
cm.ShareBox.MSG_SHARE_VIEW_LINK_ = goog.getMsg('Paste link in email or IM');

/**
 * @desc Label for the "share this map view as an iframe" field.
 * @private
 */
cm.ShareBox.MSG_SHARE_VIEW_IFRAME_ = goog.getMsg(
    'Paste HTML to embed in website');
