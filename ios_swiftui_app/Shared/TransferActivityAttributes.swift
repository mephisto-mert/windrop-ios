import ActivityKit
import Foundation

@available(iOS 16.2, *)
struct TransferActivityAttributes: ActivityAttributes {
    public struct ContentState: Codable, Hashable {
        var fileName: String
        var progress: Double
        var speedMBps: Double
        var doneCount: Int
        var totalCount: Int
        var isCompleted: Bool
    }

    var pcName: String
}
