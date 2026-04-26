class AnyType(str):
    """Compares equal to any other type string in ComfyUI's frontend type-equality
    check. The standard pattern across ComfyUI custom nodes; the frontend tests
    `their_type != our_type` when wiring, so overriding `__ne__` to always return
    False makes connections from any source accept.
    """

    def __ne__(self, _other: object) -> bool:
        return False


ANY = AnyType("*")
