#! /usr/bin/env python3

class DeferrableExecutionQueue:
    """
    An execution wrapper which defers the execution of statements until the
    queue is full.

    This is useful to aggregate the values from Python generators to utilize
    the *executemany* execution strategy.

    .. note::
        If multiple different statements are being deferred, their queues are
        executed in the same order they were added, so statements from the
        second queue can depend on the statements from the first queue and so
        on. As soon as the size of any queue reaches the size limit, all queues
        are executed - otherwise the queues may get out of sync and execution
        may hit constraint errors.

    :param sqlalchemy.engine.Connection conn:
        a connection (with an established transaction) to the database where the
        statements are executed
    :param int chunk_size:
        maximum queue size
    """
    def __init__(self, conn, chunk_size):
        if chunk_size <= 0:  # pragma: no cover
            raise ValueError("chunk_size must be positive")

        self.conn = conn
        self.chunk_size = chunk_size

        # used for preserving order or executed statements
        # (an OrderedDict won't help because we need to clear the dict and
        # still preserve the keys that we remove)
        self.ordered_keys = []
        self.stmt_queues = {}

    def execute(self, statement, *multiparams, **params):
        """
        Adds a statement into the execution queue.

        The semantics of the parameters is the same as of
        :py:meth:`sqlalchemy.engine.Connection.execute`.
        """
        if self.chunk_size == 1:
            self.conn.execute(statement, *multiparams, **params)
        else:
            if statement not in self.ordered_keys:
                self.ordered_keys.append(statement)
            q = self.stmt_queues.setdefault(statement, [])
            if multiparams:
                q += multiparams
            if params:
                q.append(params)

            if len(q) >= self.chunk_size:
                self.execute_deferred()

    def execute_deferred(self):
        """
        Execute all deferred statements and clear the queue.
        """
        for statement in self.ordered_keys:
            if statement in self.stmt_queues:
                self.conn.execute(statement, self.stmt_queues[statement])

        # don't clear self.ordered_keys to preserve the order from first execution
        self.stmt_queues.clear()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.execute_deferred()
