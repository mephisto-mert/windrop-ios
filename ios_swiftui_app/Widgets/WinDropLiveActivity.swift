import ActivityKit
import SwiftUI
import WidgetKit

@main
struct WinDropWidgetsBundle: WidgetBundle {
    var body: some Widget {
        if #available(iOS 16.2, *) {
            WinDropLiveActivity()
        }
    }
}

@available(iOS 16.2, *)
struct WinDropLiveActivity: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: TransferActivityAttributes.self) { context in
            // Lock Screen / Notification Center Banner
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Image(systemName: context.state.isCompleted ? "checkmark.circle.fill" : "arrow.up.circle.fill")
                        .foregroundColor(context.state.isCompleted ? .green : .blue)
                    Text(context.state.isCompleted ? "Aktarım Tamamlandı" : "WinDrop Aktarımı • \(context.attributes.pcName)")
                        .font(.caption.bold())
                        .foregroundColor(.white)
                    Spacer()
                    Text("\(Int(context.state.progress * 100))%")
                        .font(.caption.monospacedDigit().bold())
                        .foregroundColor(.cyan)
                }

                Text(context.state.fileName)
                    .font(.subheadline.bold())
                    .foregroundColor(.white)
                    .lineLimit(1)

                ProgressView(value: context.state.progress)
                    .tint(.blue)

                HStack {
                    Text("\(context.state.doneCount)/\(max(1, context.state.totalCount)) dosya")
                        .font(.caption2)
                        .foregroundColor(.secondary)
                    Spacer()
                    Text(String(format: "%.1f MB/sn", context.state.speedMBps))
                        .font(.caption2.monospacedDigit())
                        .foregroundColor(.secondary)
                }
            }
            .padding(14)
            .activityBackgroundTint(Color.black.opacity(0.85))
            .activitySystemActionForegroundColor(.white)
        } dynamicIsland: { context in
            DynamicIsland {
                DynamicIslandExpandedRegion(.leading) {
                    Label("\(Int(context.state.progress * 100))%", systemImage: "arrow.up.circle.fill")
                        .font(.caption.bold())
                        .foregroundColor(.blue)
                }
                DynamicIslandExpandedRegion(.trailing) {
                    Text(String(format: "%.1f MB/s", context.state.speedMBps))
                        .font(.caption2.monospacedDigit())
                        .foregroundColor(.cyan)
                }
                DynamicIslandExpandedRegion(.bottom) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(context.state.fileName)
                            .font(.caption.bold())
                            .lineLimit(1)
                        ProgressView(value: context.state.progress)
                            .tint(.blue)
                    }
                }
            } compactLeading: {
                Image(systemName: "arrow.up.circle.fill")
                    .foregroundColor(.blue)
            } compactTrailing: {
                Text("\(Int(context.state.progress * 100))%")
                    .font(.caption2.monospacedDigit().bold())
                    .foregroundColor(.cyan)
            } minimal: {
                Image(systemName: "arrow.up.circle.fill")
                    .foregroundColor(.blue)
            }
        }
    }
}
