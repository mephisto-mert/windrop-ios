import Photos
import SwiftUI
import UIKit

struct ClipboardView: View {
    @ObservedObject var client: WinDropClient
    @State private var draftText: String = ""
    @State private var toastMsg: String = ""

    var body: some View {
        NavigationView {
            List {
                if !toastMsg.isEmpty {
                    Section {
                        Text(toastMsg)
                            .font(.footnote.bold())
                            .foregroundColor(.green)
                    }
                }

                Section("iPhone ➔ PC Pano / Link Gönder") {
                    TextField("Metin veya URL yapıştırın...", text: $draftText, axis: .vertical)
                        .lineLimit(2...5)

                    HStack(spacing: 10) {
                        Button {
                            if let paste = UIPasteboard.general.string, !paste.isEmpty {
                                draftText = paste
                            }
                        } label: {
                            Label("Yapıştır", systemImage: "doc.on.clipboard")
                        }
                        .buttonStyle(.bordered)

                        Button {
                            let toSend = draftText.isEmpty ? (UIPasteboard.general.string ?? "") : draftText
                            guard !toSend.isEmpty else { return }
                            Task {
                                let ok = await client.pushClipboardText(toSend)
                                toastMsg = ok ? "✅ PC panosuna gönderildi" : "❌ Gönderilemedi"
                                if ok { draftText = "" }
                            }
                        } label: {
                            Label("PC'ye Gönder", systemImage: "paperplane.fill")
                        }
                        .buttonStyle(.borderedProminent)
                    }

                    Button {
                        let raw = draftText.isEmpty ? (UIPasteboard.general.string ?? "") : draftText
                        guard !raw.isEmpty else { return }
                        Task {
                            let ok = await client.openURLOnPC(raw)
                            toastMsg = ok ? "🌐 Link PC tarayıcısında açıldı" : "⚠️ Geçerli link bulunamadı"
                        }
                    } label: {
                        Label("Linki PC Tarayıcısında Aç", systemImage: "safari.fill")
                    }
                }

                Section("PC Panosu (Canlı)") {
                    if client.pcClipboardText.isEmpty {
                        Text("PC panosu boş veya henüz okunmadı")
                            .foregroundColor(.secondary)
                    } else {
                        Text(client.pcClipboardText)
                            .font(.callout)
                            .textSelection(.enabled)
                        Button {
                            UIPasteboard.general.string = client.pcClipboardText
                            toastMsg = "📋 iPhone panosuna kopyalandı"
                        } label: {
                            Label("iPhone'a Kopyala", systemImage: "doc.on.doc.fill")
                        }
                    }
                }

                Section("PC Görsel Panosu (Ekran Görüntüsü)") {
                    if let img = client.pcClipboardImage {
                        Image(uiImage: img)
                            .resizable()
                            .scaledToFit()
                            .frame(maxHeight: 220)
                            .cornerRadius(12)

                        Button {
                            UIImageWriteToSavedPhotosAlbum(img, nil, nil, nil)
                            toastMsg = "✅ Görsel Fotoğraflar'a kaydedildi"
                        } label: {
                            Label("Fotoğraflar'a Kaydet", systemImage: "square.and.arrow.down")
                        }
                    } else {
                        Text("PC panosunda görsel bulunamadı")
                            .font(.footnote)
                            .foregroundColor(.secondary)
                    }

                    Button {
                        Task { await client.fetchClipboardImage() }
                    } label: {
                        Label("PC Görsel Panosunu Yenile", systemImage: "photo.badge.arrow.down")
                    }
                }

                if !client.clipboardHistory.isEmpty {
                    Section("Son Pano Geçmişi") {
                        ForEach(client.clipboardHistory) { item in
                            Button {
                                UIPasteboard.general.string = item.text
                                toastMsg = "📋 Kopyalandı"
                            } label: {
                                VStack(alignment: .leading, spacing: 4) {
                                    Text(item.text)
                                        .lineLimit(2)
                                        .foregroundColor(.primary)
                                    Text("\(item.source ?? "PC") • \(item.time ?? "")")
                                        .font(.caption2)
                                        .foregroundColor(.secondary)
                                }
                            }
                        }
                    }
                }
            }
            .navigationTitle("Evrensel Pano")
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button {
                        Task {
                            await client.fetchClipboard()
                            await client.fetchClipboardImage()
                        }
                    } label: {
                        Image(systemName: "arrow.clockwise")
                    }
                }
            }
            .onAppear {
                Task {
                    await client.fetchClipboard()
                    await client.fetchClipboardImage()
                }
            }
        }
    }
}
