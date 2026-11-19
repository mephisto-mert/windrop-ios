import SwiftUI

struct ContentView: View {
    @StateObject private var discovery = StudioDiscovery()
    @StateObject private var audio = OmniMicAudioEngine()
    @State private var selectedTab: Int = 0
    @State private var manualHost: String = UserDefaults.standard.string(forKey: "om_manual_host") ?? ""

    var body: some View {
        TabView(selection: $selectedTab) {
            studioTab
                .tabItem {
                    Label("Stüdyo", systemImage: "mic.fill")
                }
                .tag(0)

            dspTab
                .tabItem {
                    Label("DSP & EQ", systemImage: "slider.vertical.3")
                }
                .tag(1)

            soundboardTab
                .tabItem {
                    Label("Soundboard", systemImage: "square.grid.2x2.fill")
                }
                .tag(2)

            connectTab
                .tabItem {
                    Label("Bağlantı", systemImage: "antenna.radiowaves.left.and.right")
                }
                .tag(3)
        }
        .tint(.blue)
        .preferredColorScheme(.dark)
    }

    // MARK: - Tab 1: Stüdyo & Canlı VU

    private var studioTab: some View {
        NavigationView {
            ScrollView {
                VStack(spacing: 16) {
                    // Status Pill Card
                    VStack(spacing: 10) {
                        ZStack {
                            Circle()
                                .fill(
                                    LinearGradient(
                                        colors: audio.isTransmitting ? [.green, .teal] : [.cyan, .blue],
                                        startPoint: .top,
                                        endPoint: .bottom
                                    )
                                )
                                .frame(width: 72, height: 72)
                            Image(systemName: audio.isMuted ? "mic.slash.fill" : "mic.fill")
                                .font(.system(size: 30, weight: .bold))
                                .foregroundColor(.white)
                        }

                        Text(discovery.activeStudio?.name ?? "OmniMic Studio")
                            .font(.title3.bold())
                        Text(discovery.statusText)
                            .font(.caption)
                            .foregroundColor(discovery.activeStudio != nil ? .green : .cyan)
                    }
                    .padding()
                    .frame(maxWidth: .infinity)
                    .background(Color(UIColor.secondarySystemBackground))
                    .cornerRadius(22)

                    // Apple Sequoia VU Meter Card
                    VStack(alignment: .leading, spacing: 10) {
                        HStack {
                            Text("Canlı Ses Seviyesi")
                                .font(.headline)
                            Spacer()
                            Text(audio.currentPeakDb > -80 ? String(format: "%+.1f dBFS", audio.currentPeakDb) : "-inf dB")
                                .font(.caption.monospacedDigit().bold())
                                .foregroundColor(.cyan)
                        }

                        GeometryReader { geo in
                            let norm = max(0.0, min(1.0, Double((audio.currentRmsDb + 60.0) / 60.0)))
                            ZStack(alignment: .leading) {
                                RoundedRectangle(cornerRadius: 8)
                                    .fill(Color.white.opacity(0.08))
                                RoundedRectangle(cornerRadius: 8)
                                    .fill(
                                        LinearGradient(
                                            colors: [.green, .yellow, .red],
                                            startPoint: .leading,
                                            endPoint: .trailing
                                        )
                                    )
                                    .frame(width: max(4, geo.size.width * norm))
                                    .animation(.linear(duration: 0.06), value: norm)
                            }
                        }
                        .frame(height: 18)

                        HStack {
                            Text("Kazanç: \(String(format: "%.2fx", audio.masterGain))")
                                .font(.caption)
                                .foregroundColor(.secondary)
                            Slider(value: $audio.masterGain, in: 0.2...3.0, step: 0.05) { _ in
                                audio.setGain(audio.masterGain)
                            }
                            .tint(.blue)
                        }
                    }
                    .padding()
                    .background(Color(UIColor.secondarySystemBackground))
                    .cornerRadius(20)

                    // Main Stream Button
                    Button {
                        if audio.isTransmitting {
                            audio.stopStreaming()
                        } else if let studio = discovery.activeStudio {
                            audio.startStreaming(to: studio)
                        }
                    } label: {
                        Label(
                            audio.isTransmitting ? "Yayını Durdur" : "Canlı Mikrofonu Başlat",
                            systemImage: audio.isTransmitting ? "stop.circle.fill" : "play.circle.fill"
                        )
                        .font(.headline)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 16)
                        .background(audio.isTransmitting ? Color.red : Color.blue)
                        .foregroundColor(.white)
                        .cornerRadius(16)
                    }
                    .disabled(discovery.activeStudio == nil && !audio.isTransmitting)

                    // Mute & Record Row
                    HStack(spacing: 12) {
                        Button {
                            audio.toggleMute()
                        } label: {
                            Label(audio.isMuted ? "Sessizde" : "Mute", systemImage: audio.isMuted ? "mic.slash.fill" : "mic.fill")
                                .font(.subheadline.bold())
                                .frame(maxWidth: .infinity)
                                .padding(.vertical, 14)
                                .background(audio.isMuted ? Color.red.opacity(0.85) : Color(UIColor.secondarySystemBackground))
                                .foregroundColor(.white)
                                .cornerRadius(14)
                        }

                        Button {
                            audio.toggleRecord()
                        } label: {
                            Label(audio.isRecording ? "Kaydı Bitir" : "PC Kayıt", systemImage: audio.isRecording ? "stop.fill" : "record.circle")
                                .font(.subheadline.bold())
                                .frame(maxWidth: .infinity)
                                .padding(.vertical, 14)
                                .background(audio.isRecording ? Color.orange : Color(UIColor.secondarySystemBackground))
                                .foregroundColor(.white)
                                .cornerRadius(14)
                        }
                    }
                }
                .padding()
            }
            .navigationTitle("OmniMic Studio")
        }
    }

    // MARK: - Tab 2: DSP & Profiller

    private var dspTab: some View {
        NavigationView {
            Form {
                Section("Gerçek Zamanlı Ses İşleme (DSP)") {
                    Toggle("Spectral Denoise (%50 OLA)", isOn: $audio.denoiseEnabled)
                        .onChange(of: audio.denoiseEnabled) { _ in audio.syncDSP() }
                    Toggle("Dynamic De-Esser", isOn: $audio.deesserEnabled)
                        .onChange(of: audio.deesserEnabled) { _ in audio.syncDSP() }
                    Toggle("Anti-Howling (Uğultu Önleyici)", isOn: $audio.antiHowlingEnabled)
                        .onChange(of: audio.antiHowlingEnabled) { _ in audio.syncDSP() }
                }

                Section("Stüdyo Ses Profilleri (EQ)") {
                    let profiles: [(String, String)] = [
                        ("studio_clean", "🎙️ Studio Clean"),
                        ("warm_podcast", "🔥 Warm Podcast"),
                        ("tactical_fps", "🎯 Tactical FPS"),
                        ("walkie_talkie", "📻 Walkie Talkie"),
                        ("radio_host", "📡 Radio Host"),
                    ]
                    ForEach(profiles, id: \.0) { pid, title in
                        Button {
                            audio.setProfile(pid)
                        } label: {
                            HStack {
                                Text(title).foregroundColor(.primary)
                                Spacer()
                                if audio.activeProfile == pid {
                                    Image(systemName: "checkmark.circle.fill").foregroundColor(.blue)
                                }
                            }
                        }
                    }
                }
            }
            .navigationTitle("DSP & Profiller")
        }
    }

    // MARK: - Tab 3: Soundboard

    private var soundboardTab: some View {
        NavigationView {
            ScrollView {
                LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 14) {
                    let items: [(String, String, Color)] = [
                        ("horn", "📣 Airhorn", .orange),
                        ("chime", "🔔 Chime", .blue),
                        ("applause", "👏 Alkış", .green),
                        ("beep", "🤬 Sansür Bip", .red),
                    ]
                    ForEach(items, id: \.0) { sid, title, col in
                        Button {
                            audio.playSound(sid)
                        } label: {
                            VStack(spacing: 8) {
                                Text(title)
                                    .font(.headline)
                                    .foregroundColor(.white)
                            }
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 28)
                            .background(col.opacity(0.28))
                            .overlay(RoundedRectangle(cornerRadius: 18).stroke(col.opacity(0.6), lineWidth: 1))
                            .cornerRadius(18)
                        }
                    }
                }
                .padding()
            }
            .navigationTitle("Soundboard")
        }
    }

    // MARK: - Tab 4: Bağlantı & Token

    private var connectTab: some View {
        NavigationView {
            Form {
                Section("Bulunan Stüdyolar") {
                    if discovery.discoveredStudios.isEmpty {
                        Text("Henüz PC bulunamadı")
                            .foregroundColor(.secondary)
                    } else {
                        ForEach(discovery.discoveredStudios) { st in
                            Button {
                                discovery.activeStudio = st
                                discovery.statusText = "🟢 \(st.name) • \(st.via)"
                            } label: {
                                HStack {
                                    VStack(alignment: .leading) {
                                        Text(st.name).foregroundColor(.primary).font(.subheadline.bold())
                                        Text("\(st.via) • \(st.baseURL)").font(.caption2).foregroundColor(.secondary)
                                    }
                                    Spacer()
                                    if discovery.activeStudio?.id == st.id {
                                        Image(systemName: "checkmark.circle.fill").foregroundColor(.green)
                                    }
                                }
                            }
                        }
                    }
                    Button("Yeniden Tara (Wi-Fi + Bulut)") {
                        discovery.startDiscovery()
                    }
                }

                Section("Manuel Bağlantı (IP:Port veya Tünel)") {
                    TextField("Örn: 192.168.1.158:8125", text: $manualHost)
                        .keyboardType(.URL)
                        .autocapitalization(.none)
                        .disableAutocorrection(true)
                    Button("Bağlan") {
                        Task { _ = await discovery.connectManual(manualHost) }
                    }
                }

                Section(
                    header: Text("Tünel Güvenlik Tokeni (4G/5G)"),
                    footer: Text("Ev Wi-Fi'ında gerekmez. Dış ağdan bağlanırken PC'deki OmniMic Studio uygulamasından 'Tünel Tokenini Kopyala' butonunu kullanın.")
                ) {
                    SecureField("X-OmniMic-Token", text: $audio.deviceToken)
                        .autocapitalization(.none)
                        .disableAutocorrection(true)
                }
            }
            .navigationTitle("Bağlantı & Ayarlar")
        }
    }
}
