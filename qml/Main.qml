/*
 * Seal VPN for Proton -- the screen.
 * Sign in with a Proton account, then connect to any Proton VPN server.
 * ../host/sealvpn.py runs Proton's own Linux client code (the official CLI's
 * controller), so connections are made exactly as Proton's CLI makes them and
 * keep running with the app closed.
 */
import QtQuick 2.12
import Lomiri.Components 1.3
import Lomiri.Components.Popups 1.3
import io.thp.pyotherside 1.4

MainView {
    id: root
    objectName: "mainView"
    applicationName: "sealvpn.jeffbristow"
    anchorToKeyboard: true
    width: units.gu(45)
    height: units.gu(80)

    readonly property color cGood: "#1f8a4c"
    readonly property color cWait: "#b7791f"
    readonly property color cOff: "#3b414b"
    readonly property color cBlock: "#b03a2e"
    readonly property color cAccent: "#6d4aff"

    property bool started: false
    property string startError: ""
    property var st: ({ loggedIn: false, account: "", tier: 0, state: "DISCONNECTED", server: null, rx: 0, tx: 0 })
    property var cfg: ({ killswitch: 0 })
    property var ip: ({ ok: false, ip: "", place: "", isp: "" })
    property bool ipChecking: false
    property var recentServers: []
    property var manualVpns: []
    property bool busy: false
    property string busyText: ""
    property string appVersion: ""
    property string protonVersion: ""

    readonly property bool connected: st.state === "CONNECTED"
    readonly property bool connecting: st.state === "CONNECTING" || st.state === "DISCONNECTING"
    readonly property bool paid: st.tier > 0

    Component.onCompleted: theme.name = "Lomiri.Components.Themes.SuruDark"

    function tierName(t) { return ["Free", "Basic", "Plus", "Proton"][t] || ("Plan " + t) }
    function fmtBytes(b) {
        if (b < 1024) return b + " B"
        if (b < 1048576) return (b / 1024).toFixed(1) + " KB"
        if (b < 1073741824) return (b / 1048576).toFixed(1) + " MB"
        return (b / 1073741824).toFixed(2) + " GB"
    }
    function loadColor(l) { return l < 50 ? cGood : l < 80 ? cWait : cBlock }
    function where(s) {
        if (!s) return ""
        var w = (s.city ? s.city + ", " : "") + (s.countryName || s.country || "")
        if (s.entry && s.country && s.entry !== s.country) w += " via " + (s.entryName || s.entry)
        return w
    }

    function refresh() {
        py.call("sealvpn.status", [], function (r) { if (r && r.ok) st = r })
        py.call("sealvpn.recent", [], function (r) { recentServers = r || [] })
    }
    function loadSettings(done) {
        py.call("sealvpn.settings", [], function (r) { if (r && r.ok) cfg = r; if (done) done() })
    }
    function checkIp() { ipChecking = true; py.call("sealvpn.check_ip", []) }

    function act(fn, args, text, done) {
        busy = true; busyText = text || ""
        py.call("sealvpn." + fn, args, function (r) {
            busy = false
            if (r && !r.ok) toast.show(r.error)
            else if (r && r.warning) toast.show(r.warning)
            refresh()
            if (done) done(r)
        })
    }
    function connectTo(target, label) { act("connect", [target], "Connecting to " + label + "…") }

    Timer { interval: 3000; running: started && st.loggedIn && Qt.application.active; repeat: true; onTriggered: refresh() }
    Connections {
        target: Qt.application
        onActiveChanged: if (Qt.application.active && started && st.loggedIn) { refresh(); checkIp() }
    }

    PageStack { id: stack }

    function showMain() {
        stack.clear()
        if (st.loggedIn) { stack.push(homePage); loadSettings(); checkIp() }
        else stack.push(signInPage)
    }

    /* ======================================================== LOADING */
    Rectangle {
        anchors.fill: parent
        visible: !started
        color: theme.palette.normal.background
        Column {
            anchors.centerIn: parent
            spacing: units.gu(2)
            width: parent.width - units.gu(6)
            Image { source: "../assets/icon.svg"; width: units.gu(10); height: width; anchors.horizontalCenter: parent.horizontalCenter }
            ActivityIndicator { running: startError === ""; visible: running; anchors.horizontalCenter: parent.horizontalCenter }
            Label {
                width: parent.width; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap
                text: startError === "" ? "Starting Proton VPN…" : "Couldn't start: " + startError
            }
            Button {
                visible: startError !== ""; text: "Try again"; anchors.horizontalCenter: parent.horizontalCenter
                onClicked: { startError = ""; py.start() }
            }
        }
    }

    /* ======================================================== SIGN IN */
    Component {
        id: signInPage
        Page {
            id: sp
            property bool need2fa: false
            property string err: ""
            header: PageHeader { title: "Seal VPN"; subtitle: "for Proton" }
            Flickable {
                anchors { fill: parent; topMargin: parent.header.height }
                contentHeight: scol.height + units.gu(6)
                Column {
                    id: scol
                    x: units.gu(3); width: parent.width - units.gu(6)
                    spacing: units.gu(1.5)
                    topPadding: units.gu(3)
                    Image { source: "../assets/icon.svg"; width: units.gu(9); height: width; anchors.horizontalCenter: parent.horizontalCenter }
                    Label {
                        width: parent.width; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap
                        textSize: Label.Large; font.weight: Font.DemiBold
                        text: sp.need2fa ? "Two-factor authentication" : "Sign in with your Proton account"
                    }
                    Label {
                        width: parent.width; wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter
                        color: theme.palette.normal.backgroundSecondaryText
                        text: sp.need2fa ? "Enter the 6-digit code from your authenticator app (or a recovery code)."
                                         : "Your password goes straight to Proton, using Proton VPN's own Linux client. The session is kept in the phone's keyring."
                    }
                    TextField {
                        id: user; width: parent.width; visible: !sp.need2fa
                        placeholderText: "Username or email"
                        inputMethodHints: Qt.ImhNoAutoUppercase | Qt.ImhNoPredictiveText | Qt.ImhEmailCharactersOnly
                        onAccepted: pass.forceActiveFocus()
                    }
                    TextField {
                        id: pass; width: parent.width; visible: !sp.need2fa
                        placeholderText: "Password"; echoMode: TextInput.Password
                        inputMethodHints: Qt.ImhNoAutoUppercase | Qt.ImhNoPredictiveText | Qt.ImhSensitiveData
                        onAccepted: signIn.clicked()
                    }
                    TextField {
                        id: code; width: parent.width; visible: sp.need2fa
                        placeholderText: "123456"
                        inputMethodHints: Qt.ImhNoPredictiveText | Qt.ImhPreferNumbers
                        onAccepted: signIn.clicked()
                    }
                    Label { visible: sp.err !== ""; text: sp.err; color: theme.palette.normal.negative; width: parent.width; wrapMode: Text.WordWrap }
                    Button {
                        id: signIn
                        width: parent.width; color: cAccent; enabled: !busy
                        text: sp.need2fa ? "Verify" : "Sign in"
                        onClicked: {
                            sp.err = ""
                            if (!sp.need2fa) {
                                if (!user.text.trim() || !pass.text) { sp.err = "Enter your username and password."; return }
                                busy = true; busyText = "Signing in…"
                                py.call("sealvpn.login", [user.text, pass.text], function (r) {
                                    busy = false
                                    if (!r.ok) { sp.err = r.error; return }
                                    pass.text = ""
                                    if (r.twofa) { sp.need2fa = true; code.forceActiveFocus() }
                                    else signedIn()
                                })
                            } else {
                                busy = true; busyText = "Verifying…"
                                py.call("sealvpn.submit_2fa", [code.text], function (r) {
                                    busy = false
                                    if (!r.ok) { sp.err = r.error; code.text = ""; return }
                                    signedIn()
                                })
                            }
                        }
                    }
                    Button {
                        visible: sp.need2fa; width: parent.width; text: "Start over"
                        onClicked: { sp.need2fa = false; code.text = ""; sp.err = "" }
                    }
                    Label {
                        width: parent.width; wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter
                        color: theme.palette.normal.backgroundTertiaryText
                        text: "Security keys (FIDO2) can't be used on the phone: use an authenticator code."
                    }
                }
            }
        }
    }
    function signedIn() {
        py.call("sealvpn.status", [], function (r) { if (r && r.ok) st = r; showMain() })
    }

    /* ======================================================== HOME */
    Component {
        id: homePage
        Page {
            header: PageHeader {
                title: "Seal VPN"
                subtitle: st.account ? st.account + " · " + tierName(st.tier) : "for Proton"
                trailingActionBar.actions: [
                    Action { iconName: "settings"; text: "Settings"; onTriggered: { loadSettings(); stack.push(settingsPage) } },
                    Action { iconName: "info"; text: "About"; onTriggered: stack.push(aboutPage) }
                ]
            }
            Flickable {
                anchors { fill: parent; topMargin: parent.header.height }
                contentHeight: col.height + units.gu(4)
                clip: true
                Column {
                    id: col
                    width: parent.width
                    spacing: units.gu(1.5)
                    topPadding: units.gu(2)

                    // ---------- a manually imported tunnel would fight with Proton's
                    Rectangle {
                        visible: manualVpns.length > 0
                        x: units.gu(2); width: parent.width - units.gu(4)
                        height: mcol.height + units.gu(3); radius: units.gu(1)
                        color: "#3d2f12"
                        Column {
                            id: mcol
                            anchors { left: parent.left; right: parent.right; top: parent.top; margins: units.gu(1.5) }
                            spacing: units.gu(1)
                            Label {
                                width: parent.width; wrapMode: Text.WordWrap; color: "white"
                                text: "Another WireGuard VPN is set up on this phone (" + manualVpns.map(function (v) { return v.name }).join(", ")
                                    + "). It can connect at the same time as Seal VPN and clash with it. Remove it so only Seal VPN manages your VPN?"
                            }
                            Row {
                                spacing: units.gu(1)
                                Button {
                                    text: "Remove"; color: cBlock
                                    onClicked: {
                                        var list = manualVpns.slice()
                                        manualVpns = []
                                        for (var i = 0; i < list.length; i++) py.call("sealvpn.remove_manual_vpn", [list[i].uuid], function (r) { if (!r.ok) toast.show(r.error) })
                                        toast.show("Removed")
                                    }
                                }
                                Button { text: "Keep"; onClicked: manualVpns = [] }
                            }
                        }
                    }

                    // ---------- status card
                    Rectangle {
                        id: card
                        x: units.gu(2); width: parent.width - units.gu(4)
                        height: cardCol.height + units.gu(4)
                        radius: units.gu(1.5)
                        readonly property bool blocking: !connected && !connecting && cfg.killswitch === 2
                        color: connected ? cGood : connecting ? cWait : st.state === "ERROR" || blocking ? cBlock : cOff
                        Behavior on color { ColorAnimation { duration: 250 } }
                        Column {
                            id: cardCol
                            anchors { left: parent.left; right: parent.right; top: parent.top; margins: units.gu(2) }
                            spacing: units.gu(0.8)
                            Row {
                                spacing: units.gu(1.5)
                                Icon {
                                    width: units.gu(5); height: width; color: "white"
                                    name: connected ? "lock" : connecting ? "sync" : card.blocking || st.state === "ERROR" ? "security-alert" : "lock-broken"
                                }
                                Column {
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: cardCol.width - units.gu(7)
                                    Label {
                                        textSize: Label.Large; font.weight: Font.DemiBold; color: "white"
                                        text: connected ? "Protected" : st.state === "DISCONNECTING" ? "Disconnecting…" : connecting ? "Connecting…"
                                            : st.state === "ERROR" ? "Connection problem" : card.blocking ? "Internet blocked" : "Not protected"
                                    }
                                    Label {
                                        color: "#e8ffffff"; width: parent.width; wrapMode: Text.WordWrap
                                        text: st.server ? st.server.name + "  ·  " + where(st.server)
                                            : card.blocking ? "Advanced kill switch: no internet until you connect"
                                            : "Connect to a Proton VPN server"
                                    }
                                }
                            }
                            Label {
                                visible: connected && st.server && st.server.load !== undefined
                                color: "#e8ffffff"
                                text: st.server ? ("Server load " + st.server.load + "%" + (st.server.features && st.server.features.length ? "  ·  " + st.server.features.join(", ") : "")) : ""
                            }
                            Label {
                                visible: ip.ok || ipChecking || ip.error !== undefined
                                color: "white"; width: parent.width; wrapMode: Text.WordWrap
                                text: ipChecking && !ip.ip ? "Checking your public IP…"
                                    : ip.ok ? "Public IP " + ip.ip + (ip.place ? "  ·  " + ip.place : "") + (ip.isp ? "  ·  " + ip.isp : "")
                                    : "Public IP: " + (ip.error || "unknown")
                            }
                            Label { visible: connected; color: "#e8ffffff"; text: "↓ " + fmtBytes(st.rx) + "    ↑ " + fmtBytes(st.tx) }
                            Item { width: 1; height: units.gu(0.5) }
                            Row {
                                spacing: units.gu(1)
                                Button {
                                    text: connected || connecting ? "Disconnect" : "Quick connect"
                                    color: "white"; enabled: !busy
                                    onClicked: connected || connecting ? act("disconnect", [], "Disconnecting…") : connectTo({}, "the fastest server")
                                }
                                Button { text: "Check IP"; enabled: !ipChecking; onClicked: checkIp() }
                            }
                        }
                    }

                    // ---------- choose
                    ListItem {
                        height: l1.height + (divider.visible ? divider.height : 0)
                        onClicked: stack.push(countriesPage)
                        ListItemLayout {
                            id: l1
                            title.text: "All countries"
                            subtitle.text: "Choose a country, city or server"
                            Icon { name: "location"; width: units.gu(3); SlotsLayout.position: SlotsLayout.Leading }
                            ProgressionSlot {}
                        }
                    }
                    Label { x: units.gu(2); text: "Profiles"; font.weight: Font.DemiBold; color: theme.palette.normal.backgroundSecondaryText }
                    Repeater {
                        model: [
                            { t: "Fastest server", s: "Lowest load near you", target: {}, plus: false, icon: "flash-on" },
                            { t: "P2P", s: "Fastest server for file sharing", target: { feature: "p2p" }, plus: true, icon: "share" },
                            { t: "Secure Core", s: "Through Proton's hardened servers first", target: { feature: "securecore" }, plus: true, icon: "security-alert" },
                            { t: "Tor", s: "Tor over VPN (.onion sites)", target: { feature: "tor" }, plus: true, icon: "network-vpn" }
                        ]
                        delegate: ListItem {
                            height: pl.height + (divider.visible ? divider.height : 0)
                            enabled: !modelData.plus || paid
                            onClicked: connectTo(modelData.target, modelData.t)
                            ListItemLayout {
                                id: pl
                                title.text: modelData.t
                                subtitle.text: modelData.plus && !paid ? "Needs a paid plan" : modelData.s
                                Icon { name: modelData.icon; width: units.gu(3); SlotsLayout.position: SlotsLayout.Leading }
                            }
                        }
                    }
                    Label {
                        x: units.gu(2); text: "Recent"; font.weight: Font.DemiBold; color: theme.palette.normal.backgroundSecondaryText
                        visible: recentServers.length > 0
                    }
                    Repeater {
                        model: recentServers
                        delegate: ListItem {
                            height: rl.height + (divider.visible ? divider.height : 0)
                            onClicked: connectTo({ server: modelData.name }, modelData.name)
                            ListItemLayout {
                                id: rl
                                title.text: modelData.name
                                subtitle.text: where(modelData)
                                summary.text: st.server && st.server.name === modelData.name && connected ? "Connected" : ""
                                summary.color: cGood
                                Icon { name: "history"; width: units.gu(3); SlotsLayout.position: SlotsLayout.Leading }
                            }
                        }
                    }
                    ListItem {
                        height: ksl.height + (divider.visible ? divider.height : 0)
                        onClicked: { loadSettings(); stack.push(settingsPage) }
                        ListItemLayout {
                            id: ksl
                            title.text: "Kill switch: " + ["off", "standard", "advanced"][cfg.killswitch || 0]
                            subtitle.text: ["Internet works without the VPN", "Blocks the internet if the VPN drops", "No internet unless the VPN is connected"][cfg.killswitch || 0]
                            Icon { name: "security-alert"; width: units.gu(3); SlotsLayout.position: SlotsLayout.Leading; color: cfg.killswitch ? cAccent : theme.palette.normal.backgroundSecondaryText }
                            ProgressionSlot {}
                        }
                    }
                }
            }
        }
    }

    /* ======================================================== COUNTRIES */
    Component {
        id: countriesPage
        Page {
            id: cp
            property var all: []
            property bool loading: true
            property string err: ""
            Component.onCompleted: py.call("sealvpn.countries", [], function (r) {
                loading = false
                if (r.ok) all = r.countries; else err = r.error
            })
            readonly property var shown: {
                var q = search.text.trim().toLowerCase()
                if (!q) return all
                return all.filter(function (c) { return c.name.toLowerCase().indexOf(q) >= 0 || c.code.toLowerCase() === q })
            }
            header: PageHeader {
                title: "Countries"
                contents: TextField {
                    id: search
                    anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter }
                    placeholderText: "Search countries"
                    inputMethodHints: Qt.ImhNoPredictiveText
                }
            }
            ActivityIndicator { anchors.centerIn: parent; running: cp.loading }
            Label { anchors.centerIn: parent; visible: cp.err !== ""; text: cp.err; width: parent.width - units.gu(4); wrapMode: Text.WordWrap }
            ListView {
                anchors { fill: parent; topMargin: cp.header.height }
                clip: true
                model: cp.shown
                delegate: ListItem {
                    height: cl.height + (divider.visible ? divider.height : 0)
                    enabled: modelData.available > 0
                    onClicked: stack.push(countryPage, { country: modelData })
                    ListItemLayout {
                        id: cl
                        title.text: modelData.name
                        subtitle.text: modelData.available > 0
                            ? modelData.available + " servers" + (modelData.cities > 1 ? " in " + modelData.cities + " cities" : "")
                              + (modelData.features.length ? "  ·  " + modelData.features.filter(function (f) { return f !== "IPv6" }).join(", ") : "")
                            : (paid ? "Unavailable" : "Needs a paid plan")
                        summary.text: modelData.available > 0 ? modelData.bestLoad + "%" : ""
                        summary.color: loadColor(modelData.bestLoad)
                        Label { text: modelData.code; width: units.gu(4); font.weight: Font.DemiBold; SlotsLayout.position: SlotsLayout.Leading }
                        ProgressionSlot {}
                    }
                }
            }
        }
    }

    Component {
        id: countryPage
        Page {
            id: kp
            property var country: ({})
            property bool loading: true
            ListModel { id: srvModel }
            Component.onCompleted: py.call("sealvpn.servers", [country.code], function (r) {
                loading = false
                if (!r.ok) { toast.show(r.error); return }
                var rows = []
                for (var i = 0; i < r.servers.length; i++) {
                    var s = r.servers[i]
                    rows.push({ name: s.name, city: s.city, country: s.country, entry: s.entry, entryName: s.entryName,
                                load: s.load, feat: s.feat, enabled: s.enabled, locked: s.locked })
                }
                srvModel.append(rows)
            })
            header: PageHeader { title: kp.country.name || "" }
            ActivityIndicator { anchors.centerIn: parent; running: kp.loading }
            ListView {
                id: lv
                anchors { fill: parent; topMargin: kp.header.height }
                clip: true
                model: srvModel
                header: Column {
                    width: lv.width
                    spacing: units.gu(1)
                    topPadding: units.gu(1.5); bottomPadding: units.gu(1)
                    Button {
                        x: units.gu(2); width: parent.width - units.gu(4); color: cAccent
                        text: "Fastest in " + (kp.country.name || ""); enabled: !busy
                        onClicked: connectTo({ country: kp.country.code }, kp.country.name)
                    }
                    Button {
                        visible: (kp.country.features || []).indexOf("Secure Core") >= 0 && paid
                        x: units.gu(2); width: parent.width - units.gu(4)
                        text: "Secure Core to " + (kp.country.name || ""); enabled: !busy
                        onClicked: connectTo({ country: kp.country.code, feature: "securecore" }, "Secure Core " + kp.country.name)
                    }
                    Button {
                        visible: (kp.country.features || []).indexOf("P2P") >= 0 && paid
                        x: units.gu(2); width: parent.width - units.gu(4)
                        text: "Fastest P2P in " + (kp.country.name || ""); enabled: !busy
                        onClicked: connectTo({ country: kp.country.code, feature: "p2p" }, "P2P " + kp.country.name)
                    }
                }
                section.property: "city"
                section.criteria: ViewSection.FullString
                section.delegate: ListItem {
                    height: units.gu(6)
                    color: theme.palette.normal.base
                    onClicked: if (section) connectTo({ country: kp.country.code, city: section }, section)
                    Label { anchors { left: parent.left; leftMargin: units.gu(2); verticalCenter: parent.verticalCenter }
                            text: section || "Other servers"; font.weight: Font.DemiBold }
                    Label { anchors { right: parent.right; rightMargin: units.gu(2); verticalCenter: parent.verticalCenter }
                            visible: !!section; text: "Fastest here ›"; color: cAccent }
                }
                delegate: ListItem {
                    height: sl.height + (divider.visible ? divider.height : 0)
                    enabled: model.enabled && !model.locked
                    onClicked: connectTo({ server: model.name }, model.name)
                    ListItemLayout {
                        id: sl
                        title.text: model.name + (st.server && st.server.name === model.name && connected ? "  ✓" : "")
                        subtitle.text: !model.enabled ? "Under maintenance" : model.locked ? "Needs a higher plan"
                            : (model.entry !== model.country ? "Secure Core via " + model.entryName + (model.feat ? "  ·  " : "") : "") + model.feat
                        summary.text: model.enabled ? model.load + "%" : ""
                        summary.color: loadColor(model.load)
                        Rectangle {
                            SlotsLayout.position: SlotsLayout.Leading
                            width: units.gu(0.6); height: units.gu(3.5); radius: width / 2
                            color: model.enabled ? loadColor(model.load) : cOff
                        }
                    }
                }
            }
        }
    }

    /* ======================================================== SETTINGS */
    Component {
        id: settingsPage
        Page {
            id: setp
            header: PageHeader { title: "Settings" }
            function save(path, value) {
                act("set_setting", [path, value], path === "killswitch" && connected ? "Applying (reconnecting)…" : "Saving…", function () { loadSettings() })
            }
            Flickable {
                anchors { fill: parent; topMargin: parent.header.height }
                contentHeight: gcol.height + units.gu(4)
                clip: true
                Column {
                    id: gcol
                    x: units.gu(2); width: parent.width - units.gu(4)
                    spacing: units.gu(1.5)
                    topPadding: units.gu(2)

                    OptionSelector {
                        text: "Kill switch"
                        model: ["Off", "Standard — blocks the internet if the VPN drops", "Advanced — no internet unless the VPN is connected"]
                        selectedIndex: cfg.killswitch || 0
                        expanded: true
                        onDelegateClicked: if (index !== cfg.killswitch) save("killswitch", index)
                    }
                    Label {
                        width: parent.width; wrapMode: Text.WordWrap; color: theme.palette.normal.backgroundSecondaryText
                        text: "Proton's own kill switch. Advanced stays on after a restart: with it, the phone has no internet at all (WiFi or mobile data) until the VPN connects — pair it with Connect at startup."
                    }

                    OptionSelector {
                        text: "NetShield" + (paid ? "" : " (paid plans)")
                        enabled: paid
                        model: ["Off", "Block malware", "Block malware, ads and trackers"]
                        selectedIndex: cfg.netshield || 0
                        onDelegateClicked: if (index !== cfg.netshield) save("features.netshield", index)
                    }

                    Repeater {
                        model: [
                            { k: "features.vpn_accelerator", p: "vpn_accelerator", t: "VPN Accelerator", s: "Faster connections over long distances", paid: true },
                            { k: "features.moderate_nat", p: "moderate_nat", t: "Moderate NAT", s: "For gaming and calls that need direct connections", paid: true },
                            { k: "features.port_forwarding", p: "port_forwarding", t: "Port forwarding", s: "For P2P servers", paid: true },
                            { k: "ipv6", p: "ipv6", t: "IPv6", s: "Use IPv6 through the VPN", paid: false },
                            { k: "anonymous_crash_reports", p: "anonymous_crash_reports", t: "Send anonymous crash reports to Proton", s: "From Proton's client code", paid: false }
                        ]
                        delegate: Item {
                            width: gcol.width; height: Math.max(sw.height, tcol.height) + units.gu(1)
                            Column {
                                id: tcol
                                anchors { left: parent.left; right: sw.left; rightMargin: units.gu(1); verticalCenter: parent.verticalCenter }
                                Label { text: modelData.t; width: parent.width; wrapMode: Text.WordWrap }
                                Label { text: modelData.paid && !paid ? "Paid plans" : modelData.s; width: parent.width; wrapMode: Text.WordWrap; textSize: Label.Small; color: theme.palette.normal.backgroundSecondaryText }
                            }
                            Switch {
                                id: sw
                                anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                                enabled: !modelData.paid || paid
                                checked: !!cfg[modelData.p]
                                onClicked: { var v = checked; checked = Qt.binding(function () { return !!cfg[modelData.p] }); setp.save(modelData.k, v) }
                            }
                        }
                    }

                    Item {
                        width: parent.width; height: Math.max(dsw.height, dl.height) + units.gu(1)
                        Label {
                            id: dl
                            anchors { left: parent.left; verticalCenter: parent.verticalCenter }
                            text: "Custom DNS" + (paid ? "" : " (paid plans)")
                        }
                        Switch {
                            id: dsw; anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                            enabled: paid; checked: !!cfg.custom_dns
                            onClicked: {
                                var v = checked; checked = Qt.binding(function () { return !!cfg.custom_dns })
                                if (v && !dnsField.text.trim()) { toast.show("Enter the DNS addresses first"); return }
                                act("set_custom_dns", [v, dnsField.text], "Saving…", function () { loadSettings() })
                            }
                        }
                    }
                    TextField {
                        id: dnsField; width: parent.width; enabled: paid
                        text: cfg.custom_dns_ips || ""
                        placeholderText: "e.g. 9.9.9.9, 149.112.112.112"
                        inputMethodHints: Qt.ImhNoAutoUppercase | Qt.ImhNoPredictiveText
                    }
                    Button {
                        visible: !!cfg.custom_dns && dnsField.text !== (cfg.custom_dns_ips || "")
                        text: "Save DNS"
                        onClicked: act("set_custom_dns", [true, dnsField.text], "Saving…", function () { loadSettings() })
                    }

                    OptionSelector {
                        id: startSel
                        text: "Connect at startup"
                        model: ["Off", "Fastest server", "Last server used", "Fastest in a country…"]
                        readonly property var modes: ["off", "fastest", "last", "country"]
                        selectedIndex: Math.max(0, modes.indexOf(cfg.startup || "off"))
                        onDelegateClicked: {
                            var m = modes[index]
                            if (m === "country") { startCountry.forceActiveFocus(); if (!startCountry.text.trim()) { toast.show("Type a country code (e.g. US) below, then Save"); return } }
                            act("set_startup", [m, startCountry.text.trim().toUpperCase()], "Saving…", function () { loadSettings() })
                        }
                    }
                    Row {
                        spacing: units.gu(1)
                        visible: startSel.selectedIndex === 3 || cfg.startup === "country"
                        TextField { id: startCountry; width: units.gu(10); text: cfg.startupCountry || ""; placeholderText: "US"; inputMethodHints: Qt.ImhUppercaseOnly | Qt.ImhNoPredictiveText }
                        Button { text: "Save"; onClicked: act("set_startup", ["country", startCountry.text.trim().toUpperCase()], "Saving…", function () { loadSettings() }) }
                    }
                    Label {
                        width: parent.width; wrapMode: Text.WordWrap; color: theme.palette.normal.backgroundSecondaryText
                        text: "Connects after the phone starts, once it has a network."
                    }

                    Item { width: 1; height: units.gu(1) }
                    Label { text: "Account"; font.weight: Font.DemiBold }
                    Label { text: st.account + "  ·  " + tierName(st.tier) + " plan"; color: theme.palette.normal.backgroundSecondaryText }
                    Button {
                        width: parent.width; text: "Sign out"; color: theme.palette.normal.negative
                        onClicked: PopupUtils.open(signOutDialog)
                    }
                }
            }
        }
    }

    Component {
        id: signOutDialog
        Dialog {
            id: sd
            title: "Sign out?"
            text: "This disconnects the VPN, turns off Connect at startup and removes your Proton session from the phone."
                + (cfg.killswitch === 2 ? "\n\nThe advanced kill switch stays as it is; turn it off first if you want normal internet." : "")
            Button {
                text: "Sign out"; color: theme.palette.normal.negative
                onClicked: { PopupUtils.close(sd); act("logout", [], "Signing out…", function (r) { if (r.ok) { st = { loggedIn: false, tier: 0, state: "DISCONNECTED" }; showMain() } }) }
            }
            Button { text: "Cancel"; onClicked: PopupUtils.close(sd) }
        }
    }

    /* ======================================================== ABOUT */
    Component {
        id: aboutPage
        Page {
            header: PageHeader { title: "About" }
            Flickable {
                anchors { fill: parent; topMargin: parent.header.height }
                contentHeight: acol.height + units.gu(4)
                clip: true
                Column {
                    id: acol
                    x: units.gu(2); width: parent.width - units.gu(4)
                    spacing: units.gu(1.5)
                    topPadding: units.gu(2)
                    Label { text: "Seal VPN for Proton " + appVersion; textSize: Label.Large; font.weight: Font.DemiBold }
                    Label { text: "Proton VPN client: " + protonVersion; color: theme.palette.normal.backgroundSecondaryText }
                    Label {
                        width: parent.width; wrapMode: Text.WordWrap
                        text: "A touch front end for Proton VPN's official Linux client (the Proton VPN CLI and the libraries it's built on, GPLv3, bundled unchanged). "
                            + "Signing in, servers, WireGuard keys, connections, the kill switch and NetShield are Proton's own code; "
                            + "connections are made with the phone's NetworkManager and keep running with the app closed.\n\n"
                            + "Not available on the phone: split tunneling (needs a kernel feature this phone lacks) and security-key sign-in.\n\n"
                            + "If you're ever stuck without internet because of the advanced kill switch, set it to Off in Settings, "
                            + "or in the Terminal app run:\nnmcli connection delete pvpn-killswitch-perm\n\n"
                            + "Not made by or affiliated with Proton AG. Proton VPN is a trademark of Proton AG."
                    }
                }
            }
        }
    }

    /* ======================================================== BUSY + TOAST */
    Rectangle {
        anchors.fill: parent
        visible: busy
        color: "#99000000"
        MouseArea { anchors.fill: parent }
        Column {
            anchors.centerIn: parent
            spacing: units.gu(1.5)
            ActivityIndicator { anchors.horizontalCenter: parent.horizontalCenter; running: busy }
            Label { anchors.horizontalCenter: parent.horizontalCenter; text: busyText; color: "white" }
        }
    }

    Rectangle {
        id: toast
        property alias text: tl.text
        function show(t) { text = t; opacity = 1; tt.restart() }
        anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: units.gu(4) }
        width: Math.min(parent.width - units.gu(4), tl.implicitWidth + units.gu(4))
        height: tl.height + units.gu(2.4)
        radius: units.gu(1)
        color: "#ee222428"
        opacity: 0
        visible: opacity > 0
        Behavior on opacity { NumberAnimation { duration: 200 } }
        Label { id: tl; anchors.centerIn: parent; width: Math.min(implicitWidth, root.width - units.gu(8)); wrapMode: Text.WordWrap; color: "white" }
        Timer { id: tt; interval: 5000; onTriggered: toast.opacity = 0 }
    }

    /* ======================================================== PYTHON */
    Python {
        id: py
        function start() {
            call("sealvpn.start", [], function (r) {
                if (!r.ok) { startError = r.error; return }
                st = r
                manualVpns = r.manualVpns || []
                started = true
                showMain()
                if (r.cleanup && r.cleanup.length) toast.show(r.cleanup.join(" "))
            })
        }
        Component.onCompleted: {
            addImportPath(Qt.resolvedUrl("../host"))
            setHandler("ip", function (r) { ipChecking = false; ip = r })
            setHandler("state", function (s) {
                var n = {}
                for (var k in st) n[k] = st[k]
                n.state = s.state; n.server = s.server
                st = n
            })
            importModule("sealvpn", function () {
                call("sealvpn.version", [], function (v) { appVersion = v })
                call("sealvpn.proton_version", [], function (v) { protonVersion = v })
                start()
            })
        }
        onError: { console.log("SealVPN py: " + traceback); toast.show("Internal error — see the log") }
    }
}
