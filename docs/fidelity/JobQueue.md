# JobQueue fidelity

The active supplied adapter uses one Redis Stream and one consumer group. It proves local
publication, consumption, pending-message claiming after 30 seconds, three bounded delivery
attempts, acknowledgement after terminal persistence, and deterministic restart behavior.

Redis Streams is not equivalent to Amazon SQS. This local implementation does not claim managed-service
visibility, IAM enforcement, dead-letter behavior, durability guarantees, availability, or cost.
There is no Redis dead-letter queue and no parallel queue implementation in this Sprint.

The single Redis container has no replication, backup, authentication, load qualification, or
production availability guarantee. Stream length is exposed only as a local diagnostic; without a
retention policy it is not a count of outstanding work and grows as messages are appended.
