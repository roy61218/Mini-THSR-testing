class ApiError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def invalid(message):
    return ApiError(422, "INVALID_PARAMETER", message)


def not_found(message):
    return ApiError(404, "NOT_FOUND", message)
