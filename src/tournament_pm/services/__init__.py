"""Use cases. Each public function is one database transaction: it commits fully or not at all.

Services take a session *factory* rather than a session so the transaction boundary is
visible right here (`with factory.begin() as session:`), not hidden in the web layer.
"""
