"""Visual system for the XUANSHU LAB desktop shell."""

APP_STYLESHEET = r"""
* {
    font-family: "Microsoft YaHei UI", "Segoe UI";
    font-size: 13px;
    color: #102846;
}
QMainWindow, QWidget#appRoot, QStackedWidget#contentStack {
    background: #F3F7FC;
}
QFrame#sideRail {
    background: #071C38;
    border: none;
}
QLabel#brandChinese {
    color: #FFFFFF;
    font-size: 22px;
    font-weight: 800;
    letter-spacing: 3px;
}
QLabel#brandEnglish {
    color: #68AFFF;
    font-family: "Cascadia Mono";
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 2px;
}
QLabel#railSection {
    color: #6F89A8;
    font-family: "Cascadia Mono";
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 2px;
    padding: 16px 12px 7px 12px;
}
QPushButton#navButton {
    min-height: 46px;
    padding: 0 14px;
    border: 1px solid transparent;
    border-radius: 9px;
    background: transparent;
    color: #AFC2D9;
    text-align: left;
    font-size: 13px;
    font-weight: 600;
}
QPushButton#navButton:hover {
    background: rgba(71, 142, 225, 0.12);
    color: #FFFFFF;
}
QPushButton#navButton:checked {
    border-color: rgba(102, 179, 255, 0.20);
    background: #12365F;
    color: #FFFFFF;
}
QFrame#railRuntime {
    border: 1px solid #1D4169;
    border-radius: 10px;
    background: #0B294D;
}
QLabel#railRuntimeTitle {
    color: #FFFFFF;
    font-family: "Cascadia Mono";
    font-size: 9px;
    font-weight: 700;
}
QLabel#railRuntimeCopy {
    color: #7E9AB8;
    font-size: 10px;
}
QFrame#topBar {
    background: rgba(255, 255, 255, 0.96);
    border-bottom: 1px solid #D9E5F1;
}
QLabel#pageEyebrow {
    color: #1677E8;
    font-family: "Cascadia Mono";
    font-size: 9px;
    font-weight: 800;
    letter-spacing: 1px;
}
QLabel#pageTitle {
    color: #071C38;
    font-size: 21px;
    font-weight: 750;
}
QLabel#pageSubtitle {
    color: #72869E;
    font-size: 11px;
}
QLabel#statusPillReady, QLabel#statusPillWaiting {
    padding: 7px 12px;
    border-radius: 14px;
    font-family: "Cascadia Mono";
    font-size: 9px;
    font-weight: 700;
}
QLabel#statusPillReady {
    border: 1px solid #A7E1D3;
    background: #ECFAF6;
    color: #147B68;
}
QLabel#statusPillWaiting {
    border: 1px solid #E6D1A6;
    background: #FFF8EA;
    color: #9A6819;
}
QPushButton#toolButton, QPushButton#primaryButton, QPushButton#ghostButton {
    min-height: 34px;
    padding: 0 13px;
    border-radius: 7px;
    font-size: 11px;
    font-weight: 650;
}
QPushButton#toolButton, QPushButton#ghostButton {
    border: 1px solid #CBDCEA;
    background: #FFFFFF;
    color: #3F5F82;
}
QPushButton#toolButton:hover, QPushButton#ghostButton:hover {
    border-color: #8AB8E9;
    background: #F2F8FF;
    color: #1168CF;
}
QPushButton#primaryButton {
    border: 1px solid #146EDA;
    background: #1677E8;
    color: #FFFFFF;
}
QPushButton#primaryButton:hover { background: #0E66CD; }
QScrollArea#overviewScroll, QScrollArea#previewScroll {
    border: none;
    background: transparent;
}
QWidget#overviewPage, QWidget#previewPage, QWidget#scrollBody {
    background: #F3F7FC;
}
QFrame#heroPanel {
    border: 1px solid #C6DCF1;
    border-radius: 16px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #FFFFFF, stop:0.55 #F3F9FF, stop:1 #E9F5FF);
}
QLabel#heroKicker {
    color: #1677E8;
    font-family: "Cascadia Mono";
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 2px;
}
QLabel#heroTitle {
    color: #071C38;
    font-size: 34px;
    font-weight: 780;
}
QLabel#heroTitleAccent {
    color: #1677E8;
    font-size: 34px;
    font-weight: 780;
}
QLabel#heroCopy {
    color: #637B96;
    font-size: 13px;
    line-height: 1.6;
}
QLabel#metricNumber {
    color: #0B355F;
    font-family: "Cascadia Mono";
    font-size: 22px;
    font-weight: 800;
}
QLabel#metricLabel {
    color: #7890AA;
    font-family: "Cascadia Mono";
    font-size: 8px;
    font-weight: 700;
}
QLabel#sectionTitle {
    color: #0A2446;
    font-size: 18px;
    font-weight: 750;
}
QLabel#sectionCopy {
    color: #7A8EA5;
    font-size: 11px;
}
QFrame#workspaceCard {
    border: 1px solid #D1DFEC;
    border-radius: 13px;
    background: #FFFFFF;
}
QFrame#workspaceCard:hover {
    border-color: #83B7ED;
    background: #FDFEFF;
}
QLabel#cardCategory {
    font-family: "Cascadia Mono";
    font-size: 8px;
    font-weight: 800;
    letter-spacing: 1px;
}
QLabel#cardName {
    color: #0A2446;
    font-size: 20px;
    font-weight: 750;
}
QLabel#cardEnglish {
    color: #577493;
    font-size: 11px;
    font-weight: 650;
}
QLabel#cardDescription {
    color: #758AA1;
    font-size: 11px;
}
QLabel#capabilityTag {
    padding: 4px 7px;
    border: 1px solid #D5E4F1;
    border-radius: 4px;
    background: #F5F9FD;
    color: #55728F;
    font-family: "Cascadia Mono";
    font-size: 8px;
}
QLabel#previewBadge {
    padding: 5px 9px;
    border: 1px solid #E0CDF9;
    border-radius: 10px;
    background: #F8F1FF;
    color: #7951B2;
    font-family: "Cascadia Mono";
    font-size: 8px;
    font-weight: 700;
}
QFrame#webContainer {
    border: 1px solid #CFDDEA;
    border-radius: 11px;
    background: #FFFFFF;
}
QFrame#webToolbar {
    border-bottom: 1px solid #DCE6EF;
    background: #F8FBFE;
}
QLabel#webAddress {
    padding: 6px 10px;
    border: 1px solid #D3E0EC;
    border-radius: 6px;
    background: #FFFFFF;
    color: #68819B;
    font-family: "Cascadia Mono";
    font-size: 9px;
}
QWebEngineView { background: #FFFFFF; }
QFrame#previewHero {
    border: 1px solid #D8C6EF;
    border-radius: 16px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #FFFFFF, stop:0.55 #F7F2FD, stop:1 #EEF4FF);
}
QLabel#previewTitle {
    color: #25123F;
    font-size: 36px;
    font-weight: 780;
}
QLabel#previewAccent {
    color: #8055BF;
    font-size: 36px;
    font-weight: 780;
}
QFrame#conceptCard, QFrame#roadmapRow {
    border: 1px solid #D8E2EC;
    border-radius: 11px;
    background: #FFFFFF;
}
QLabel#conceptIndex {
    color: #8055BF;
    font-family: "Cascadia Mono";
    font-size: 10px;
    font-weight: 800;
}
QLabel#conceptTitle {
    color: #172D49;
    font-size: 15px;
    font-weight: 750;
}
QLabel#conceptCopy, QLabel#roadmapCopy {
    color: #74869A;
    font-size: 10px;
}
QDockWidget {
    color: #D7E6F5;
    font-size: 11px;
    font-weight: 700;
}
QDockWidget::title {
    padding: 7px 10px;
    background: #0A2446;
    text-align: left;
}
QPlainTextEdit#logView {
    border: none;
    background: #07192F;
    color: #AFC8E3;
    font-family: "Cascadia Mono";
    font-size: 10px;
    selection-background-color: #145CA7;
}
QStatusBar {
    border-top: 1px solid #D7E3EE;
    background: #F8FBFE;
    color: #6F849B;
    font-size: 10px;
}
QDialog { background: #FFFFFF; }
QMessageBox QLabel { min-width: 340px; }
QToolTip {
    border: 1px solid #9BB9D8;
    padding: 5px;
    background: #FFFFFF;
    color: #173757;
}
"""
