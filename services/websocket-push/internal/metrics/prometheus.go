package metrics

import (
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
)

var (
	WebSocketConnections = promauto.NewGauge(prometheus.GaugeOpts{
		Name: "fl_websocket_connections",
		Help: "Number of active WebSocket connections",
	})

	MessagesBroadcast = promauto.NewCounter(prometheus.CounterOpts{
		Name: "fl_websocket_messages_broadcast_total",
		Help: "Total number of messages broadcast to WebSocket clients",
	})

	EventsReceived = promauto.NewCounterVec(prometheus.CounterOpts{
		Name: "fl_websocket_events_received_total",
		Help: "Total number of Redis pub/sub events received by type",
	}, []string{"event"})
)
