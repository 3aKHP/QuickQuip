class TiebaServiceError(RuntimeError):
    pass


class TiebaLoginRequiredError(TiebaServiceError):
    pass
