import PhotosUI
import SwiftUI
import UniformTypeIdentifiers

@main
struct WinDropApp: App {
    @StateObject private var client = WinDropClient()

    var body: some Scene {
        WindowGroup {
            MainTabView(client: client)
                .preferredColorScheme(.dark)
                .onOpenURL { url in
                    client.handleDeepLink(url)
                }
        }
    }
}

struct MainTabView: View {
    @ObservedObject var client: WinDropClient
    @State private var selectedTab: Int = 0

    var body: some View {
        TabView(selection: $selectedTab) {
            RadarView(client: client)
                .tabItem {
                    Label("AirDrop", systemImage: "antenna.radiowaves.left.and.right")
                }
                .tag(0)

            RemoteDesktopView(client: client)
                .tabItem {
                    Label("Uzak Ekran", systemImage: "desktopcomputer")
                }
                .tag(1)

            ClipboardView(client: client)
                .tabItem {
                    Label("Pano", systemImage: "doc.on.clipboard")
                }
                .tag(2)

            SettingsView(client: client)
                .tabItem {
                    Label("Ayarlar", systemImage: "gearshape.fill")
                }
                .tag(3)
        }
        .tint(.blue)
    }
}

// MARK: - Tab 1: Radar & Unlimited Lossless Transfer

struct RadarView: View {
    @ObservedObject var client: WinDropClient
    @State private var selectedPhotos: [PhotosPickerItem] = []
    @State private var showFileImporter: Bool = false
    @State private var isPreparingMedia: Bool = false
    @State private var downloadNotice: String = ""
    @State private var pulse: Bool = false

    var body: some View {
        NavigationView {
            ScrollView {
                VStack(spacing: 16) {
                    // AirDrop Radar Card
                    VStack(spacing: 12) {
                        ZStack {
                            Circle()
                                .stroke(Color.blue.opacity(0.22), lineWidth: 2)
                                .frame(width: 136, height: 136)
                                .scaleEffect(pulse ? 1.08 : 0.96)
                            Circle()
                                .stroke(Color.blue.opacity(0.42), lineWidth: 2)
                                .frame(width: 96, height: 96)
                            Circle()
                                .fill(LinearGradient(colors: [Color(red: 0.04, green: 0.52, blue: 1.0), Color(red: 0.0, green: 0.25, blue: 0.87)], startPoint: .top, endPoint: .bottom))
                                .frame(width: 58, height: 58)
                            Image(systemName: client.isConnected ? "desktopcomputer" : "antenna.radiowaves.left.and.right")
                                .font(.system(size: 24, weight: .bold))
                                .foregroundColor(.white)
                        }
                        .onAppear {
                            withAnimation(.easeInOut(duration: 1.8).repeatForever(autoreverses: true)) {
                                pulse = true
                            }
                        }

                        Text(client.activePeer?.name ?? "WinDrop Canlı Radar")
                            .font(.title3.bold())
                        Text(client.connectionStatus)
                            .font(.caption)
                            .foregroundColor(client.isConnected ? .green : .cyan)
                            .multilineTextAlignment(.center)
                    }
                    .padding()
                    .frame(maxWidth: .infinity)
                    .background(Color(UIColor.secondarySystemBackground))
                    .cornerRadius(22)

                    // Unlimited Lossless Pickers
                    HStack(spacing: 12) {
                        PhotosPicker(
                            selection: $selectedPhotos,
                            matching: .any(of: [.images, .videos]),
                            photoLibrary: .shared()
                        ) {
                            VStack(spacing: 6) {
                                Image(systemName: "photo.stack.fill")
                                    .font(.title2)
                                Text("Fotoğraf / Video")
                                    .font(.subheadline.bold())
                                Text("Sınırsız • Kayıpsız HEIC/4K")
                                    .font(.caption2)
                                    .opacity(0.85)
                            }
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 16)
                            .background(Color.blue)
                            .foregroundColor(.white)
                            .cornerRadius(18)
                        }
                        .onChange(of: selectedPhotos) { newItems in
                            guard !newItems.isEmpty else { return }
                            let batch = newItems
                            selectedPhotos = []
                            prepareAndEnqueuePhotos(batch)
                        }

                        Button {
                            showFileImporter = true
                        } label: {
                            VStack(spacing: 6) {
                                Image(systemName: "folder.fill")
                                    .font(.title2)
                                Text("Dosyalar'dan Seç")
                                    .font(.subheadline.bold())
                                Text("Sınırsız • 8 MB Parçalı")
                                    .font(.caption2)
                                    .opacity(0.85)
                            }
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 16)
                            .background(Color.indigo)
                            .foregroundColor(.white)
                            .cornerRadius(18)
                        }
                    }

                    // Active Queue Progress Card
                    if isPreparingMedia || client.isUploading {
                        VStack(alignment: .leading, spacing: 8) {
                            HStack {
                                Text(isPreparingMedia ? "Orijinal medya hazırlanıyor..." : "(\(client.uploadDoneCount)/\(max(client.uploadDoneCount, client.uploadTotalCount))) \(client.uploadFileName)")
                                    .font(.caption.bold())
                                    .lineLimit(1)
                                Spacer()
                                if client.isUploading {
                                    Text("\(String(format: "%.1f", client.uploadSpeedMBps)) MB/sn")
                                        .font(.caption.monospacedDigit())
                                        .foregroundColor(.cyan)
                                    Button("İptal") {
                                        client.cancelUploads()
                                    }
                                    .font(.caption.bold())
                                    .foregroundColor(.red)
                                }
                            }
                            ProgressView(value: client.uploadProgress)
                                .tint(.green)
                        }
                        .padding()
                        .background(Color(UIColor.secondarySystemBackground))
                        .cornerRadius(16)
                    }

                    if !downloadNotice.isEmpty {
                        Text(downloadNotice)
                            .font(.caption.bold())
                            .foregroundColor(.green)
                    }

                    // Discovered & Offline Saved PCs (with Wake-on-LAN)
                    if !client.discoveredPeers.isEmpty || !client.offlineSavedPeers.isEmpty {
                        VStack(alignment: .leading, spacing: 8) {
                            Text("Bulunan Bilgisayarlar")
                                .font(.headline)
                            ForEach(client.discoveredPeers) { peer in
                                Button {
                                    client.selectPeer(peer)
                                } label: {
                                    HStack {
                                        Image(systemName: peer.isTunnel ? "globe" : "wifi")
                                            .foregroundColor(peer.isTunnel ? .cyan : .green)
                                        VStack(alignment: .leading) {
                                            Text(peer.name)
                                                .font(.subheadline.bold())
                                                .foregroundColor(.primary)
                                            Text("\(peer.via) • \(peer.baseURL)")
                                                .font(.caption2)
                                                .foregroundColor(.secondary)
                                                .lineLimit(1)
                                        }
                                        Spacer()
                                        if client.activePeer?.id == peer.id {
                                            Image(systemName: "checkmark.circle.fill")
                                                .foregroundColor(.green)
                                        }
                                    }
                                    .padding(10)
                                    .background(Color.black.opacity(0.25))
                                    .cornerRadius(12)
                                }
                            }

                            ForEach(client.offlineSavedPeers) { saved in
                                HStack {
                                    Image(systemName: "desktopcomputer")
                                        .foregroundColor(.secondary)
                                    VStack(alignment: .leading) {
                                        Text(saved.name)
                                            .font(.subheadline.bold())
                                            .foregroundColor(.secondary)
                                        Text("Kapalı / Uykuda • \(saved.macAddress)")
                                            .font(.caption2)
                                            .foregroundColor(.secondary.opacity(0.8))
                                            .lineLimit(1)
                                    }
                                    Spacer()
                                    Button {
                                        client.sendWakeOnLan(to: saved)
                                    } label: {
                                        Label(
                                            client.wakingPeerName == saved.name ? "Uyanıyor..." : "Uyandır",
                                            systemImage: "bolt.fill"
                                        )
                                        .font(.caption.bold())
                                    }
                                    .buttonStyle(.borderedProminent)
                                    .tint(.indigo)
                                    .disabled(client.wakingPeerName == saved.name)
                                }
                                .padding(10)
                                .background(Color.black.opacity(0.15))
                                .cornerRadius(12)
                                .opacity(0.75)
                            }
                        }
                        .padding()
                        .background(Color(UIColor.secondarySystemBackground))
                        .cornerRadius(20)
                    }

                    // PC -> iPhone Outbound Files
                    if !client.outboundFiles.isEmpty {
                        VStack(alignment: .leading, spacing: 8) {
                            Text("PC'den Gelen Dosyalar")
                                .font(.headline)
                            ForEach(client.outboundFiles) { file in
                                HStack {
                                    VStack(alignment: .leading) {
                                        Text(file.name)
                                            .font(.subheadline.bold())
                                            .lineLimit(1)
                                        Text(ByteCountFormatter.string(fromByteCount: file.size, countStyle: .file))
                                            .font(.caption2)
                                            .foregroundColor(.secondary)
                                    }
                                    Spacer()
                                    Button("Kaydet") {
                                        Task {
                                            downloadNotice = "İndiriliyor: \(file.name)..."
                                            downloadNotice = await client.downloadAndSaveOutbound(file)
                                        }
                                    }
                                    .buttonStyle(.borderedProminent)
                                    .controlSize(.small)
                                }
                                .padding(8)
                                .background(Color.black.opacity(0.2))
                                .cornerRadius(12)
                            }
                        }
                        .padding()
                        .background(Color(UIColor.secondarySystemBackground))
                        .cornerRadius(20)
                    }

                    // Transfer History
                    if !client.history.isEmpty {
                        VStack(alignment: .leading, spacing: 8) {
                            Text("Aktarım Geçmişi")
                                .font(.headline)
                            ForEach(client.history.prefix(25)) { rec in
                                HStack {
                                    Image(systemName: rec.isSuccess ? "checkmark.seal.fill" : "exclamationmark.triangle.fill")
                                        .foregroundColor(rec.isSuccess ? .green : .red)
                                    VStack(alignment: .leading) {
                                        Text("\(rec.direction) • \(rec.fileName)")
                                            .font(.caption.bold())
                                            .lineLimit(1)
                                        Text(rec.detail)
                                            .font(.caption2)
                                            .foregroundColor(.secondary)
                                    }
                                    Spacer()
                                }
                                .padding(.vertical, 4)
                            }
                        }
                        .padding()
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(Color(UIColor.secondarySystemBackground))
                        .cornerRadius(20)
                    }
                }
                .padding()
            }
            .navigationTitle("WinDrop")
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button {
                        client.startDiscovery()
                    } label: {
                        Image(systemName: "arrow.clockwise")
                    }
                }
            }
            .fileImporter(
                isPresented: $showFileImporter,
                allowedContentTypes: [.item],
                allowsMultipleSelection: true
            ) { result in
                if case .success(let urls) = result {
                    client.enqueueFiles(urls, cleanupAfter: false)
                }
            }
        }
    }

    private func prepareAndEnqueuePhotos(_ items: [PhotosPickerItem]) {
        isPreparingMedia = true
        Task {
            for item in items {
                if let media = try? await item.loadTransferable(type: LosslessMediaFile.self) {
                    client.enqueueFiles([media.url], cleanupAfter: true)
                }
            }
            isPreparingMedia = false
        }
    }
}

// MARK: - Tab 4: Settings & Device Token Pairing

struct SettingsView: View {
    @ObservedObject var client: WinDropClient
    @Environment(\.openURL) private var openURL
    @State private var hostInput: String = ""
    @State private var wolMacInput: String = ""
    @State private var statusBanner: String = ""

    var body: some View {
        NavigationView {
            Form {
                Section("Doğrudan PC Bağlantısı (Wi-Fi)") {
                    TextField("Örn: 192.168.1.158:8765", text: $hostInput)
                        .keyboardType(.URL)
                        .autocapitalization(.none)
                        .disableAutocorrection(true)

                    Button("Bağlan ve Kaydet") {
                        Task {
                            let ok = await client.connectManualHost(hostInput)
                            statusBanner = ok ? "✅ Bağlandı!" : "❌ PC'ye ulaşılamadı"
                        }
                    }

                    Button("Otomatik Ara (Bonjour mDNS)") {
                        client.startDiscovery()
                        statusBanner = "🔍 Aranıyor..."
                    }

                    if !statusBanner.isEmpty {
                        Text(statusBanner)
                            .font(.caption.bold())
                            .foregroundColor(.cyan)
                    }
                }

                Section(
                    header: Text("Wake-on-LAN (MAC ile PC Uyandır)"),
                    footer: Text("PC açıkken bir kez bağlandığınızda MAC adresi otomatik kaydedilir. İsterseniz buradan manuel MAC girip uyandırabilirsiniz.")
                ) {
                    TextField("MAC Adresi (örn: 60:FF:9E:D8:E2:0E)", text: $wolMacInput)
                        .autocapitalization(.allCharacters)
                        .disableAutocorrection(true)

                    Button {
                        let mac = wolMacInput.trimmingCharacters(in: .whitespacesAndNewlines)
                        let base = client.normalizeBaseURL(hostInput.isEmpty ? "192.168.1.158" : hostInput)
                        client.sendWakeOnLan(to: SavedPeerRecord(id: "manual", name: "PC", baseURL: base, macAddress: mac))
                        statusBanner = "⚡ Wake-on-LAN paketi gönderildi"
                    } label: {
                        Label("PC'yi Uyandır (Magic Packet)", systemImage: "bolt.fill")
                    }
                    .disabled(wolMacInput.filter({ $0.isHexDigit }).count != 12)
                }

                Section(
                    header: Text("Otomatik Güncelleme (SideStore / AltStore)"),
                    footer: Text("iOS güvenlik kuralları gereği uygulama kendi ikili dosyasını doğrudan değiştiremez; SideStore/AltStore kaynağıyla Wi-Fi üzerinden kablosuz otomatik güncelleme alır.")
                ) {
                    LabeledContent("Sürüm", value: client.updateStatus)

                    Button("Güncellemeleri Denetle") {
                        Task { await client.checkAppUpdate() }
                    }

                    if !client.updateAvailableURL.isEmpty, let u = URL(string: client.updateAvailableURL) {
                        Button("Yeni Sürümü İndir / Güncelle") {
                            openURL(u)
                        }
                    }

                    Button("SideStore'a Otomatik Kaynak Ekle") {
                        let src = "https://mephisto-mert.github.io/windrop-ios/apps.json"
                        UIPasteboard.general.string = src
                        if let u = URL(string: "sidestore://source?url=\(src)"),
                           UIApplication.shared.canOpenURL(u) {
                            UIApplication.shared.open(u)
                            statusBanner = "✅ SideStore açılıyor..."
                        } else {
                            statusBanner = "📋 Kaynak linki kopyalandı! SideStore -> Sources -> + içine yapıştırın."
                        }
                    }

                    Button("AltStore'a Otomatik Kaynak Ekle") {
                        let src = "https://mephisto-mert.github.io/windrop-ios/apps.json"
                        UIPasteboard.general.string = src
                        if let u = URL(string: "altstore://source?url=\(src)"),
                           UIApplication.shared.canOpenURL(u) {
                            UIApplication.shared.open(u)
                            statusBanner = "✅ AltStore açılıyor..."
                        } else {
                            statusBanner = "📋 Kaynak linki kopyalandı! AltStore -> Sources -> + içine yapıştırın."
                        }
                    }

                    Button("Kaynak Linkini Kopyala (apps.json)") {
                        UIPasteboard.general.string = "https://mephisto-mert.github.io/windrop-ios/apps.json"
                        statusBanner = "📋 Kaynak URL panoya kopyalandı!"
                    }
                }

                Section("Uygulama Bilgisi") {
                    LabeledContent("Sürüm", value: "WinDrop iOS 4.0 (Native SwiftUI)")
                    LabeledContent("Aktarım Motoru", value: "8 MB Kayıpsız Parçalı + Uzak Ekran + WoL")
                }
            }
            .navigationTitle("Ayarlar")
            .onAppear {
                hostInput = client.manualHost
                if wolMacInput.isEmpty, let first = client.savedPeers.first {
                    wolMacInput = first.macAddress
                }
            }
        }
    }
}
