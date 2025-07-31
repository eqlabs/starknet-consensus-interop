
class CloudProvider:
    def create_instance(self, validator):
        raise NotImplementedError

    def create_volume(self, validator):
        raise NotImplementedError

    def attach_volume(self, instance, volume):
        raise NotImplementedError

    def deploy_validator(self, instance, validator):
        raise NotImplementedError

    def list_instances(self):
        raise NotImplementedError
